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

            import requests
            proxy_url = os.environ.get("OLLAMA_PROXY_URL", "")
            ollama_url = f"{proxy_url.rstrip('/')}/api/generate" if proxy_url else "http://localhost:11434/api/generate"
            
            created_products = []
            chunk_size = 10  # Back to local deepseek chunks
            
            print(f"--- Local AI Engine (DeepSeek) Started: {len(full_df)} rows ---")
            
            for i in range(0, len(full_df), chunk_size):
                chunk = full_df.iloc[i:i + chunk_size]
                chunk_csv = chunk.to_csv(index=False)
                
                print(f"[{i}/{len(full_df)}] Processing batch...")
                
                prompt = (
                    "### Task: Extract products from this CSV into a JSON array.\n"
                    "### Rules: Return ONLY valid JSON. No explanations. No <think> blocks.\n"
                    f"### Data:\n{chunk_csv}"
                )
                
                payload = {
                    "model": "deepseek-r1:7b",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 1000
                    }
                }

                try:
                    res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true", "ngrok-skip-browser-warning": "true"}, timeout=120)
                    
                    if res.status_code != 200:
                        print(f"Batch {i} failed with status {res.status_code}")
                        continue

                    ai_text = res.json().get("response", "")
                    
                    # Manual strip of <think> tags for stability
                    import re
                    ai_text = re.sub(r'<think>.*?</think>', '', ai_text, flags=re.DOTALL).strip()
                    
                    try:
                        raw_parsed = json.loads(ai_text)
                    except:
                        array_match = re.search(r'\[.*\]', ai_text, re.DOTALL)
                        if array_match:
                            raw_parsed = json.loads(array_match.group(0))
                        else: continue

                    items = raw_parsed if isinstance(raw_parsed, list) else raw_parsed.get("products", [])
                    if not isinstance(items, list): items = [items]

                    for item in items:
                        if not isinstance(item, dict): continue
                        name = str(item.get('name') or 'Unnamed')[:250]
                        
                        try:
                            # Clean price logic
                            price_raw = item.get('price')
                            if isinstance(price_raw, str):
                                price_raw = price_raw.replace('₹', '').replace('$', '').replace(',', '').strip()
                            price_val = float(price_raw) if price_raw else 0.0
                        except:
                            price_val = 0.0

                        Product.objects.update_or_create(
                            name=name,
                            defaults={
                                'description': str(item.get('description', ''))[:1000],
                                'unit_of_measurement': str(item.get('unit_of_measurement', 'unit'))[:50],
                                'price': price_val,
                                'category': str(item.get('category', 'Uncategorized'))[:200],
                            }
                        )
                        created_products.append(name)
                        
                except Exception as e:
                    print(f"Batch {i} network error: {str(e)}")
                    continue

            return Response({
                "message": f"Successfully processed {len(created_products)} products using local DeepSeek!",
                "data": created_products
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            err_resp = Response({"error": f"Server Error: {str(e)}"}, status=500)
            err_resp["Access-Control-Allow-Origin"] = "*"
            return err_resp
