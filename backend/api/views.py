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
            chunk_size = 5  # Tiny chunks are extremely fast and won't crash the local AI
            
            print(f"--- Ultra-Stable Processing Started: {len(full_df)} rows ---")
            
            for i in range(0, len(full_df), chunk_size):
                chunk = full_df.iloc[i:i + chunk_size]
                chunk_csv = chunk.to_csv(index=False)
                
                print(f"[{i}/{len(full_df)}] Processing...")
                
                prompt = f"Convert this CSV data to a JSON array of product objects. No preamble.\nCSV Data:\n{chunk_csv}"
                
                payload = {
                    "model": "deepseek-r1:7b",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json" # Putting this back but with tiny chunks it should be stable
                }

                try:
                    # Short timeout because tiny chunks should be instant
                    res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true", "ngrok-skip-browser-warning": "true"}, timeout=60)
                    
                    if res.status_code != 200:
                        print(f"Batch {i} failed ({res.status_code}). Skipping to keep connection alive.")
                        continue

                    raw_parsed = res.json().get("response", "")
                    if isinstance(raw_parsed, str):
                        raw_parsed = json.loads(raw_parsed)
                    
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
                            category=item.get('category') or 'Uncategorized',
                            defaults={
                                'description': item.get('description') or '',
                                'unit_of_measurement': item.get('unit_of_measurement') or 'unit',
                                'price': price_val
                            }
                        )
                        created_products.append(name)
                    
                    # No sleep needed for tiny batches as they aren't taxing the GPU
                except Exception as e:
                    print(f"Skipping tiny batch due to error: {str(e)}")
                    continue

            return Response({"message": f"Successfully parsed {len(created_products)} items from your file!", "data": created_products}, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({"error": f"Fatal: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
