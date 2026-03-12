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

class UploadFileView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Determine DataFrame and process in batches of 20
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

            from django.db import connection
            import requests

            proxy_url = os.environ.get("OLLAMA_PROXY_URL", "")
            ollama_url = f"{proxy_url.rstrip('/')}/api/generate" if proxy_url else "http://localhost:11434/api/generate"
            
            created_products = []
            chunk_size = 5  # Smaller batches = frequent database commits = higher stability
            total_rows = len(full_df)
            
            print(f"=== UPLOAD START: {total_rows} rows | Batches of {chunk_size} ===")
            
            for i in range(0, total_rows, chunk_size):
                # Close DB connection before a long-running AI task to prevent "server closed connection" errors
                connection.close() 
                
                chunk = full_df.iloc[i:i + chunk_size]
                chunk_csv = chunk.to_csv(index=False)
                
                percent = round((i / total_rows) * 100)
                print(f"[{percent}%] Processing rows {i} to {min(i+chunk_size, total_rows)}...")
                
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

                try:
                    # 5 rows should never take more than 90 seconds
                    res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true", "ngrok-skip-browser-warning": "true"}, timeout=90)
                    
                    if res.status_code != 200:
                        print(f"   ! Error: AI Batch {i} failed (Status {res.status_code})")
                        continue

                    ai_text = res.json().get("response", "")
                    
                    # Clean the response
                    import re
                    ai_text = re.sub(r'<think>.*?</think>', '', ai_text, flags=re.DOTALL).strip()
                    
                    try:
                        raw_parsed = json.loads(ai_text)
                    except:
                        match = re.search(r'\[.*\]', ai_text, re.DOTALL)
                        if match: raw_parsed = json.loads(match.group(0))
                        else: continue

                    items = raw_parsed if isinstance(raw_parsed, list) else raw_parsed.get("products", [])
                    if not isinstance(items, list): items = [items]

                    # Open connection for the DB write
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
                    
                    print(f"   ✓ Batch saved. Total so far: {len(created_products)}")
                        
                except Exception as e:
                    print(f"   ! Batch failed: {str(e)}")
                    continue

            print(f"=== UPLOAD COMPLETE: {len(created_products)} products saved ===")
            
            final_resp = Response({
                "message": f"Successfully processed {len(created_products)} rows!",
                "data": created_products
            }, status=status.HTTP_201_CREATED)
            
            final_resp["Access-Control-Allow-Origin"] = "*"
            return final_resp
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            err_resp = Response({"error": f"Fatal Crash: {str(e)}"}, status=500)
            err_resp["Access-Control-Allow-Origin"] = "*"
            return err_resp
