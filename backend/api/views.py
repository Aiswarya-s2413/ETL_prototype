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
            chunk_size = 20
            
            # Batch processing loop
            for i in range(0, len(full_df), chunk_size):
                chunk = full_df.iloc[i:i + chunk_size]
                chunk_csv = chunk.to_csv(index=False)
                
                prompt = f"""
                Extract product info from this data chunk.
                Fields: name, description, unit_of_measurement, price, category.
                Return ONLY a valid JSON array of objects.
                Data:
                {chunk_csv}
                """
                
                payload = {
                    "model": "deepseek-r1:7b",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }

                try:
                    res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true", "ngrok-skip-browser-warning": "true"}, timeout=180)
                    res.raise_for_status()
                    ai_text = res.json().get("response", "")
                    parsed_chunk = json.loads(ai_text)
                    
                    if isinstance(parsed_chunk, dict):
                        if "products" in parsed_chunk and isinstance(parsed_chunk["products"], list):
                            parsed_chunk = parsed_chunk["products"]
                        else:
                            parsed_chunk = [parsed_chunk]
                    
                    if isinstance(parsed_chunk, list):
                        for item in parsed_chunk:
                            raw_price = item.get('price')
                            try:
                                price_val = abs(float(raw_price)) if raw_price is not None else 0.0
                            except (ValueError, TypeError):
                                price_val = 0.0

                            product, _ = Product.objects.update_or_create(
                                name=item.get('name') or 'Unknown Name',
                                category=item.get('category') or 'Uncategorized',
                                defaults={
                                    'description': item.get('description') or '',
                                    'unit_of_measurement': item.get('unit_of_measurement') or 'unit',
                                    'price': price_val
                                }
                            )
                            created_products.append(ProductSerializer(product).data)
                except Exception as chunk_err:
                    print(f"Error processing chunk {i}: {str(chunk_err)}")
                    continue

            return Response({"message": f"Successfully processed {len(full_df)} rows and found {len(created_products)} products!", "data": created_products}, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_msg = f"{type(e).__name__}: {str(e)}"
            return Response({"error": error_msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
