import pandas as pd
import json
import os
import google.generativeai as genai
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Product
from .serializers import ProductSerializer

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

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
            # Parse CSV or Excel
            if file_obj.name.endswith('.csv'):
                df = pd.read_csv(file_obj)
            elif file_obj.name.endswith('.xlsx') or file_obj.name.endswith('.xls'):
                df = pd.read_excel(file_obj)
            else:
                 return Response({"error": "Unsupported file format. Please upload CSV or Excel."}, status=status.HTTP_400_BAD_REQUEST)
            
            # Sub-sample data to prevent hitting LLM context limits if the file is massive
            # In a real app, you might chunk this
            df_sample = df.head(100)
            raw_data = df_sample.to_csv(index=False)
            
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
            
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(prompt)
            
            import re
            # Extract JSON array robustly via regex, avoiding markdown issues
            match = re.search(r'\[.*\]', response.text, re.DOTALL)
            if not match:
                raise ValueError(f"AI returned invalid format: {response.text}")
                
            parsed_data = json.loads(match.group(0))
            
            created_products = []
            for item in parsed_data:
                # Safely parse price to prevent null IntegrityError
                raw_price = item.get('price')
                try:
                    price_val = float(raw_price) if raw_price is not None else 0.0
                except (ValueError, TypeError):
                    price_val = 0.0

                product, created = Product.objects.update_or_create(
                    name=item.get('name') or 'Unknown Name',
                    defaults={
                        'description': item.get('description') or '',
                        'unit_of_measurement': item.get('unit_of_measurement') or 'unit',
                        'price': price_val,
                        'category': item.get('category') or 'Uncategorized'
                    }
                )
                created_products.append(ProductSerializer(product).data)
                
            return Response({"message": "Successfully parsed and saved!", "data": created_products}, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_msg = f"{type(e).__name__}: {str(e)}"
            return Response({"error": error_msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
