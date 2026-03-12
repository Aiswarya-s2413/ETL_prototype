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

            # Get API Key from .env
            gemini_key = os.environ.get("GEMINI_API_KEY")
            if not gemini_key:
                 return Response({"error": "Gemini API Key missing in .env"}, status=400)

            import requests
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            
            # Process in large chunks for Gemini (100 rows per call is easy for Gemini)
            created_products = []
            chunk_size = 100 
            
            print(f"--- Gemini Engine Started: Processing {len(full_df)} rows ---")
            
            for i in range(0, len(full_df), chunk_size):
                chunk = full_df.iloc[i:i + chunk_size]
                chunk_csv = chunk.to_csv(index=False)
                
                prompt = (
                    "Extract product data from this CSV. Return ONLY a JSON array of objects. "
                    "Fields: name, description, unit_of_measurement, price, category. "
                    "Make sure price is a number. "
                    f"Data:\n{chunk_csv}"
                )

                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "response_mime_type": "application/json",
                    }
                }

                try:
                    res = requests.post(gemini_url, json=payload, timeout=60)
                    res.raise_for_status()
                    
                    data = res.json()
                    raw_text = data['candidates'][0]['content']['parts'][0]['text']
                    items = json.loads(raw_text)

                    if isinstance(items, dict):
                        items = items.get("products", []) or [items]

                    for item in items:
                        if not isinstance(item, dict): continue
                        name = str(item.get('name') or 'Unnamed')[:250]
                        
                        try:
                            Product.objects.update_or_create(
                                name=name,
                                defaults={
                                    'description': str(item.get('description', ''))[:1000],
                                    'unit_of_measurement': str(item.get('unit_of_measurement', 'unit'))[:50],
                                    'price': float(item.get('price', 0) or 0),
                                    'category': str(item.get('category', 'Uncategorized'))[:200],
                                }
                            )
                            created_products.append(name)
                        except Exception as db_e:
                            print(f"DB Error: {str(db_e)}")
                            continue

                except Exception as e:
                    print(f"Gemini Error on chunk {i}: {str(e)}")
                    continue

            return Response({
                "message": f"Success! Extracted {len(created_products)} products using Gemini 💎",
                "extracted_count": len(created_products),
                "data": created_products
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            err_resp = Response({"error": f"Internal Error: {str(e)}"}, status=500)
            err_resp["Access-Control-Allow-Origin"] = "*"
            return err_resp
