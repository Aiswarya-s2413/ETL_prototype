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

STATUS_FILE = "/tmp/etl_status.json"

def write_status(state):
    import json
    with open(STATUS_FILE, "w") as f:
        json.dump(state, f)

def get_status():
    import json
    import os
    if not os.path.exists(STATUS_FILE):
        return {"status": "idle"}
    with open(STATUS_FILE, "r") as f:
        return json.load(f)

def process_file_background(full_df):
    from django.db import connection
    import requests
    import os
    import json
    import re
    from api.models import Product
    import uuid
    import pandas as pd

    try:
        proxy_url = os.environ.get("OLLAMA_PROXY_URL", "")
        ollama_url = f"{proxy_url.rstrip('/')}/api/generate" if proxy_url else "http://localhost:11434/api/generate"
        
        total_rows = len(full_df)
        write_status({"status": "processing", "progress": 5, "total": total_rows, "extracted_count": 0})
        print(f"=== UPLOAD START: {total_rows} rows (Schema Mapping Mode) ===")
        
        # 1. Grab first 5 rows for the AI to "peek" at
        sample_df = full_df.head(5)
        sample_csv = sample_df.to_csv(index=False)
        columns_list = list(full_df.columns)
        
        prompt = (
            "You are a schema mapping assistant.\n"
            f"Here are the columns of a dataset: {columns_list}\n"
            f"Here is a 5-row sample of the data:\n{sample_csv}\n\n"
            "Map the raw dataset columns to our exact database fields: "
            "['name', 'description', 'price', 'unit_of_measurement', 'category'].\n"
            "If a field cannot be clearly mapped, use null.\n"
            "Return ONLY a JSON dictionary where the keys are our exact database fields and the values are the raw column names from the dataset. NO EXPLANATIONS. NO THINKING BLOCKS.\n"
            "Example format: {\"name\": \"Product Title\", \"description\": \"Details\", \"price\": \"Cost\", \"unit_of_measurement\": null, \"category\": \"Dept\"}"
        )
        
        payload = {
            "model": "deepseek-r1:7b",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 500}
        }

        print("Sending schema mapping request to DeepSeek...")
        res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true", "ngrok-skip-browser-warning": "true"}, timeout=120)
        res.raise_for_status()
        
        ai_text = res.json().get("response", "")
        ai_text = re.sub(r'<think>.*?</think>', '', ai_text, flags=re.DOTALL).strip()
        
        # Parse the mapping
        field_map = {}
        try:
            match = re.search(r'\{[^{}]+\}', ai_text)
            if match:
                field_map = json.loads(match.group(0))
            else:
                field_map = json.loads(ai_text)
        except Exception as e:
            print("Failed to parse mapping JSON. Fallback to default/none. Error:", e)
            
        print(f"AI Field Map: {field_map}")
        
        write_status({"status": "processing", "progress": 20, "total": total_rows, "extracted_count": 0})
            
        # 2. Iterate through the dataframe and save
        created_products = []
        name_col = field_map.get("name")
        desc_col = field_map.get("description")
        price_col = field_map.get("price")
        uom_col = field_map.get("unit_of_measurement")
        cat_col = field_map.get("category")
        
        products_to_create = []

        for i, row in full_df.iterrows():
            # Helper to get value
            def get_val(col_name, default=""):
                if col_name and col_name in row and not pd.isna(row[col_name]):
                    return row[col_name]
                return default

            raw_name = str(get_val(name_col, "")).strip()
            if not raw_name or raw_name.lower() in ['unnamed', 'unknown', 'null']:
                name_val = f"Unnamed Product {uuid.uuid4().hex[:6]}"
            else:
                name_val = raw_name[:250]
                
            try:
                price_raw = str(get_val(price_col, "0"))
                price_raw = price_raw.replace('₹', '').replace('$', '').replace(',', '').strip()
                price_val = float(price_raw) if price_raw else 0.0
            except:
                price_val = 0.0

            desc_val = str(get_val(desc_col, ""))
            if desc_val == 'None' or desc_val.lower() == 'null': desc_val = ""
                
            uom_val = str(get_val(uom_col, "unit"))
            if uom_val == 'None' or uom_val.lower() == 'null': uom_val = "unit"
                
            cat_val = str(get_val(cat_col, "Uncategorized"))
            if cat_val == 'None' or cat_val.lower() == 'null': cat_val = "Uncategorized"

            products_to_create.append(
                Product(
                    name=name_val,
                    description=desc_val[:1000],
                    unit_of_measurement=uom_val[:50],
                    price=price_val,
                    category=cat_val[:200]
                )
            )
            created_products.append(name_val)
            
            # Update status occasionally for UI via quick batches
            if i % 500 == 0 and i > 0:
                percent = 20 + round((i / total_rows) * 75)
                write_status({"status": "processing", "progress": percent, "total": total_rows, "extracted_count": len(created_products)})

        # Now execute the mega fast Bulk Create
        write_status({"status": "processing", "progress": 95, "total": total_rows, "extracted_count": len(created_products)})
        
        # We close existing connection to prevent "Server has gone away" error if the parsing loop took a few seconds
        connection.close() 
        Product.objects.bulk_create(products_to_create, batch_size=500, ignore_conflicts=True)

        write_status({"status": "completed", "progress": 100, "total": total_rows, "extracted_count": len(created_products)})
        print(f"=== UPLOAD COMPLETE: {len(created_products)} products saved using schema bulk mode! ===")

    except Exception as e:
        write_status({"status": "error", "error": f"Fatal Crash: {str(e)}"})
        print(f"Fatal crash inside worker: {str(e)}")


class UploadFileView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def get(self, request, *args, **kwargs):
        resp = Response(get_status(), status=status.HTTP_200_OK)
        resp["Access-Control-Allow-Origin"] = "*"
        return resp

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Determine DataFrame
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

            import threading
            # Start background processing thread
            # Avoid resetting if already running
            curr_status = get_status()
            if curr_status.get("status") == "processing":
                 return Response({"error": "An extraction is already running. Please wait."}, status=status.HTTP_409_CONFLICT)
                 
            write_status({"status": "processing", "progress": 0, "total": len(full_df), "extracted_count": 0})
            
            thread = threading.Thread(target=process_file_background, args=(full_df,))
            thread.daemon = True
            thread.start()

            final_resp = Response({
                "message": "File uploaded! Processing started in the background."
            }, status=status.HTTP_202_ACCEPTED)
            
            final_resp["Access-Control-Allow-Origin"] = "*"
            return final_resp
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            err_resp = Response({"error": f"Fatal Crash: {str(e)}"}, status=500)
            err_resp["Access-Control-Allow-Origin"] = "*"
            return err_resp
