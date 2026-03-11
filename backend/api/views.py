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
            chunk_size = 10  
            
            print(f"--- Hardened Extraction Started: {len(full_df)} rows ---")
            
            for i in range(0, len(full_df), chunk_size):
                chunk = full_df.iloc[i:i + chunk_size]
                chunk_csv = chunk.to_csv(index=False)
                
                print(f"[{i}/{len(full_df)}] Processing...")
                
                # SUPPRESS THINKING: Tell the model to skip the think block for speed and stability
                prompt = f"### System: You are a JSON generator. Do NOT use <think> blocks. Do NOT explain. Output ONLY a JSON array of objects.\n\n### Task: Extract products from this CSV data into a JSON array.\n\n### CSV Data:\n{chunk_csv}"
                
                payload = {
                    "model": "deepseek-r1:7b",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 1000 # Limit output to stop runaway thinking
                    }
                }

                try:
                    res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true", "ngrok-skip-browser-warning": "true"}, timeout=90)
                    
                    if res.status_code != 200:
                        print(f"Ollama failure on rows {i}: Status {res.status_code}")
                        continue

                    ai_text = res.json().get("response", "")
                    
                    # Robust parsing block
                    import re
                    processed_text = re.sub(r'<think>.*?</think>', '', ai_text, flags=re.DOTALL).strip()
                    
                    raw_parsed = None
                    try:
                        # Attempt 1: Standard JSON
                        raw_parsed = json.loads(processed_text)
                    except:
                        # Attempt 2: Extract array if possible
                        try:
                            array_match = re.search(r'\[.*\]', processed_text, re.DOTALL)
                            if array_match:
                                raw_parsed = json.loads(array_match.group(0))
                        except:
                            pass

                    if not raw_parsed:
                        print(f"Could not extract JSON from batch {i}")
                        continue

                    items = []
                    if isinstance(raw_parsed, dict):
                        items = raw_parsed.get("products", []) or [raw_parsed]
                    elif isinstance(raw_parsed, list):
                        items = raw_parsed

                    for item in items:
                        if not isinstance(item, dict): continue
                        name = item.get('name') or item.get('product_name')
                        if not name: continue
                        
                        raw_price = item.get('price') or item.get('cost')
                        try:
                            if isinstance(raw_price, str):
                                raw_price = raw_price.replace('₹', '').replace('$', '').replace(',', '').strip()
                            price_val = abs(float(raw_price)) if raw_price is not None else 0.0
                        except:
                            price_val = 0.0

                        Product.objects.update_or_create(
                            name=name,
                            category=item.get('category', 'Uncategorized'),
                            defaults={
                                'description': item.get('description', ''),
                                'unit_of_measurement': item.get('unit_of_measurement', 'unit'),
                                'price': price_val
                            }
                        )
                        created_products.append(name)
                    
                except Exception as inner_e:
                    print(f"Error in batch {i}: {str(inner_e)}")
                    continue

            return Response({
                "message": f"Successfully extracted {len(created_products)} products!",
                "data": created_products
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"error": f"Server Error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
