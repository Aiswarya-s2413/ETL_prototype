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
            chunk_size = 20  # 20 rows per chunk is the sweet spot for speed vs accuracy
            
            print(f"--- Hardened System: Processing {len(full_df)} rows in batches of {chunk_size} ---")
            
            for i in range(0, len(full_df), chunk_size):
                chunk = full_df.iloc[i:i + chunk_size]
                chunk_csv = chunk.to_csv(index=False)
                
                # Faster, more direct prompt to prevent AI runaway thinking
                prompt = (
                    "### Task: Convert CSV to JSON array of product objects.\n"
                    "### Format: [{\"name\": \"...\", \"description\": \"...\", \"unit_of_measurement\": \"...\", \"price\": 0.0, \"category\": \"...\"}]\n"
                    "### Rules: NO explanations. NO <think> tags. ONLY JSON.\n"
                    f"### CSV Data:\n{chunk_csv}"
                )
                
                payload = {
                    "model": "deepseek-r1:7b",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.0,
                        "num_predict": 2000
                    }
                }

                try:
                    res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true", "ngrok-skip-browser-warning": "true"}, timeout=120)
                    
                    if res.status_code != 200:
                        print(f"Batch {i}: Ollama Error {res.status_code}")
                        continue

                    ai_text = res.json().get("response", "")
                    
                    # Strip any accidental thinking blocks
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
                        
                        # Database Safety: Truncate and sanitize
                        name = str(item.get('name') or item.get('product_name') or 'Unnamed')[:250]
                        category = str(item.get('category') or 'Uncategorized')[:200]
                        desc = str(item.get('description') or '')[:1000]
                        uom = str(item.get('unit_of_measurement') or 'unit')[:50]
                        
                        try:
                            raw_price = item.get('price')
                            if isinstance(raw_price, str):
                                raw_price = raw_price.replace('₹', '').replace('$', '').replace(',', '').strip()
                            price_val = abs(float(raw_price)) if raw_price else 0.0
                        except:
                            price_val = 0.0

                        try:
                            Product.objects.update_or_create(
                                name=name,
                                category=category,
                                defaults={
                                    'description': desc,
                                    'unit_of_measurement': uom,
                                    'price': price_val
                                }
                            )
                            created_products.append(name)
                        except Exception as db_e:
                            print(f"DB Error on {name}: {str(db_e)}")
                            continue
                            
                except Exception as batch_e:
                    print(f"Batch {i} network error: {str(batch_e)}")
                    continue

            # Success response
            return Response({
                "message": f"Successfully processed {len(full_df)} rows!",
                "extracted_count": len(created_products),
                "data": created_products
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            err_resp = Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            # FORCE CORS headers even on error to prevent browser block
            err_resp["Access-Control-Allow-Origin"] = "https://etl-prototype.vercel.app"
            err_resp["Access-Control-Allow-Credentials"] = "true"
            return err_resp
