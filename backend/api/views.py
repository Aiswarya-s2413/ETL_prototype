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
            chunk_size = 30  # Balanced chunk size for reliability
            
            import time
            print(f"--- Starting Conservative Batch Processing: {len(full_df)} rows ---")
            
            for i in range(0, len(full_df), chunk_size):
                chunk = full_df.iloc[i:i + chunk_size]
                chunk_csv = chunk.to_csv(index=False)
                
                print(f"Processing Chunk {i//chunk_size + 1}...")
                
                prompt = f"""
                Extract EVERY product record from this CSV data.
                Return ONLY a JSON object: {{"products": [{{...}}]}} 
                Data:
                {chunk_csv}
                """
                
                payload = {
                    "model": "deepseek-r1:7b",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "num_ctx": 4096,
                        "num_predict": 2048,
                        "temperature": 0.1
                    }
                }

                try:
                    res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true", "ngrok-skip-browser-warning": "true"}, timeout=300)
                    
                    if res.status_code != 200:
                        print(f"Ollama Error {res.status_code}: {res.text}")
                        # If Ollama crashes, wait 5 seconds and skip this chunk to save the rest of the file
                        time.sleep(5)
                        continue

                    ai_text = res.json().get("response", "")
                    raw_parsed = json.loads(ai_text)
                    
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
                        except (ValueError, TypeError):
                            price_val = 0.0

                        product, _ = Product.objects.update_or_create(
                            name=name,
                            category=item.get('category') or item.get('dept') or 'Uncategorized',
                            defaults={
                                'description': item.get('description') or '',
                                'unit_of_measurement': item.get('unit_of_measurement') or 'unit',
                                'price': price_val
                            }
                        )
                        created_products.append(ProductSerializer(product).data)
                    
                    print(f"Chunk {i//chunk_size + 1}: Success.")
                    # Breathing room for the MacBook to avoid OOM/Crashes
                    time.sleep(2)

                except Exception as chunk_err:
                    print(f"Error in batch: {str(chunk_err)}")
                    time.sleep(3)
                    continue

            return Response({"message": f"Successfully processed {len(full_df)} rows and extracted {len(created_products)} products!", "data": created_products}, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
