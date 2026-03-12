import pandas as pd
import json
import os
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Product
from .serializers import ProductSerializer

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

STATUS_FILE = "/tmp/etl_status.json"

def write_status(state):
    import json
    with open(STATUS_FILE, "w") as f:
        json.dump(state, f)

def get_status():
    import json
    import os
    if not os.path.exists(STATUS_FILE):
        return {"status": "idle"}
    with open(STATUS_FILE, "r") as f:
        return json.load(f)

def process_file_background(full_df):
    from django.db import connection
    import requests
    import os
    import json
    import re
    from api.models import Product

    try:
        proxy_url = os.environ.get("OLLAMA_PROXY_URL", "")
        ollama_url = f"{proxy_url.rstrip('/')}/api/generate" if proxy_url else "http://localhost:11434/api/generate"
        
        created_products = []
        chunk_size = 5
        total_rows = len(full_df)
        
        write_status({"status": "processing", "progress": 0, "total": total_rows, "extracted_count": 0})
        print(f"=== UPLOAD START: {total_rows} rows ===")

        for i in range(0, total_rows, chunk_size):
            try:
                connection.close() 
                chunk = full_df.iloc[i:i + chunk_size]
                chunk_csv = chunk.to_csv(index=False)
                
                percent = round((i / total_rows) * 100)
                write_status({"status": "processing", "progress": percent, "total": total_rows, "extracted_count": len(created_products)})
                
                prompt = (
                    "### Task: Convert CSV to JSON array of product objects.\n"
                    "### Schema: [{\"name\":\"...\",\"description\":\"...\",\"unit_of_measurement\":\"...\",\"price\":0.0,\"category\":\"...\"}]\n"
                    "### Rules: NO preamble. NO thinking blocks. ONLY the JSON list.\n"
                    f"### Data:\n{chunk_csv}"
                )
                
                payload = {
                    "model": "deepseek-r1:7b",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1, "num_predict": 1000}
                }

                res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true", "ngrok-skip-browser-warning": "true"}, timeout=90)
                if res.status_code != 200: continue

                ai_text = res.json().get("response", "")
                ai_text = re.sub(r'<think>.*?</think>', '', ai_text, flags=re.DOTALL).strip()
                
                try:
                    raw_parsed = json.loads(ai_text)
                except:
                    match = re.search(r'\[.*\]', ai_text, re.DOTALL)
                    if match: raw_parsed = json.loads(match.group(0))
                    else: continue

                items = raw_parsed if isinstance(raw_parsed, list) else raw_parsed.get("products", [])
                if not isinstance(items, list): items = [items]

                for item in items:
                    if not isinstance(item, dict): continue
                    name_val = str(item.get('name') or 'Unnamed')[:250]
                    
                    try:
                        price_raw = item.get('price')
                        if isinstance(price_raw, str):
                            price_raw = price_raw.replace('₹', '').replace('$', '').replace(',', '').strip()
                        price_val = float(price_raw) if price_raw else 0.0
                    except:
                        price_val = 0.0

                    Product.objects.update_or_create(
                        name=name_val,
                        defaults={
                            'description': str(item.get('description', ''))[:1000],
                            'unit_of_measurement': str(item.get('unit_of_measurement', 'unit'))[:50],
                            'price': price_val,
                            'category': str(item.get('category', 'Uncategorized'))[:200],
                        }
                    )
                    created_products.append(name_val)
                    
            except Exception as e:
                print(f"Batch failed: {str(e)}")
                continue

        write_status({"status": "completed", "progress": 100, "total": total_rows, "extracted_count": len(created_products)})
        print(f"=== UPLOAD COMPLETE: {len(created_products)} products saved ===")

    except Exception as e:
        write_status({"status": "error", "error": f"Fatal Crash: {str(e)}"})
        print(f"Fatal crash inside worker: {str(e)}")


class UploadFileView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def get(self, request, *args, **kwargs):
        resp = Response(get_status(), status=status.HTTP_200_OK)
        resp["Access-Control-Allow-Origin"] = "*"
        return resp

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Determine DataFrame
            if file_obj.name.endswith('.csv'):
                full_df = pd.read_csv(file_obj)
            elif file_obj.name.endswith('.xlsx') or file_obj.name.endswith('.xls'):
                full_df = pd.read_excel(file_obj, engine="openpyxl")
            elif file_obj.name.endswith('.json'):
                try:
                    data = json.load(file_obj)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, list):
                                data = v
                                break
                    full_df = pd.DataFrame(data)
                except Exception:
                    file_obj.seek(0)
                    raw_content = file_obj.read().decode('utf-8', errors='ignore')[:15000]
                    full_df = pd.DataFrame([{"raw_data": raw_content}])
            else:
                 return Response({"error": "Unsupported file format."}, status=status.HTTP_400_BAD_REQUEST)

            import threading
            # Start background processing thread
            # Avoid resetting if already running
            curr_status = get_status()
            if curr_status.get("status") == "processing":
                 return Response({"error": "An extraction is already running. Please wait."}, status=status.HTTP_409_CONFLICT)
                 
            write_status({"status": "processing", "progress": 0, "total": len(full_df), "extracted_count": 0})
            
            thread = threading.Thread(target=process_file_background, args=(full_df,))
            thread.daemon = True
            thread.start()

            final_resp = Response({
                "message": "File uploaded! Processing started in the background."
            }, status=status.HTTP_202_ACCEPTED)
            
            final_resp["Access-Control-Allow-Origin"] = "*"
            return final_resp
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            err_resp = Response({"error": f"Fatal Crash: {str(e)}"}, status=500)
            err_resp["Access-Control-Allow-Origin"] = "*"
            return err_resp
