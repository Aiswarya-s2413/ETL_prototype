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
            # Parse CSV, Excel, or JSON
            if file_obj.name.endswith('.csv'):
                df = pd.read_csv(file_obj)
                raw_data = df.head(100).to_csv(index=False)
            elif file_obj.name.endswith('.xlsx') or file_obj.name.endswith('.xls'):
                df = pd.read_excel(file_obj)
                raw_data = df.head(100).to_csv(index=False)
            elif file_obj.name.endswith('.json'):
                try:
                    data = json.load(file_obj)
                    if isinstance(data, dict):
                        # try to find a list inside
                        for k, v in data.items():
                            if isinstance(v, list):
                                data = v
                                break
                    if isinstance(data, list):
                        df = pd.DataFrame(data)
                        raw_data = df.head(100).to_csv(index=False)
                    else:
                        raw_data = json.dumps(data)
                except Exception:
                    file_obj.seek(0)
                    raw_content = file_obj.read().decode('utf-8', errors='ignore')
                    raw_data = raw_content[:15000] # Provide up to 15,000 characters of the raw messy JSON
            else:
                 return Response({"error": "Unsupported file format. Please upload CSV, Excel, or JSON."}, status=status.HTTP_400_BAD_REQUEST)
            
            prompt = f"""
            I have some unstructured raw data. Please extract the product information from this data.
            Map the data to the following fields for each product:
            - name (string)
            - description (string, can be null)
            - unit_of_measurement (string)
            - price (number/float)
            - category (string)
            
            Return the result ONLY as a valid JSON array of objects. Do not wrap it in markdown block.
            Data:
            {raw_data}
            """
            
            import requests
            # Use Local Tunnel pointing to MacBook's Ollama 
            ollama_url = "https://etl-ollama-mac.loca.lt/api/generate"
            payload = {
                "model": "deepseek-r1:7b", 
                "prompt": prompt,
                "stream": False
            }
            res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true"}, timeout=120)
            res.raise_for_status()
            ai_text = res.json().get("response", "")
            
            import re
            # Extract JSON array robustly via regex, avoiding markdown issues
            match = re.search(r'\[.*\]', ai_text, re.DOTALL)
            if not match:
                raise ValueError(f"AI returned invalid format: {ai_text}")
                
            parsed_data = json.loads(match.group(0))
            
            created_products = []
            for item in parsed_data:
                # Safely parse price to prevent null IntegrityError
                raw_price = item.get('price')
                try:
                    price_val = abs(float(raw_price)) if raw_price is not None else 0.0
                except (ValueError, TypeError):
                    price_val = 0.0

                product, created = Product.objects.update_or_create(
                    name=item.get('name') or 'Unknown Name',
                    category=item.get('category') or 'Uncategorized',
                    defaults={
                        'description': item.get('description') or '',
                        'unit_of_measurement': item.get('unit_of_measurement') or 'unit',
                        'price': price_val
                    }
                )
                created_products.append(ProductSerializer(product).data)
                
            return Response({"message": "Successfully parsed and saved!", "data": created_products}, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_msg = f"{type(e).__name__}: {str(e)}"
            return Response({"error": error_msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
