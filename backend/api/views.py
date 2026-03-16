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

def process_file_background(file_path, file_extension):
    from django.db import connection
    from api.models import Product, SchemaCache
    import requests
    import os
    import json
    import re
    import uuid
    import hashlib
    import csv
    import pandas as pd

    try:
        write_status({"status": "processing", "progress": 5, "total": "Calculating...", "extracted_count": 0})
        print(f"=== UPLOAD START: {file_path} (Streaming Mode) ===")
        
        # 1. Peek at first 5 rows & get column names
        sample_rows = []
        columns_list = []
        total_rows_est = 0
        df = None # For non-csv fallbacks
        
        if file_extension == 'csv':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.DictReader(f)
                columns_list = list(reader.fieldnames or [])
                for i, row in enumerate(reader):
                    if i < 5: sample_rows.append(row)
                    total_rows_est += 1
        elif file_extension in ['xlsx', 'xls']:
            df = pd.read_excel(file_path, engine="openpyxl")
            columns_list = list(df.columns)
            sample_rows = df.head(5).to_dict('records')
            total_rows_est = len(df)
        elif file_extension == 'json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, list):
                            data = v
                            break
                df = pd.DataFrame(data)
                columns_list = list(df.columns)
                sample_rows = df.head(5).to_dict('records')
                total_rows_est = len(df)

        if not columns_list:
            raise Exception("No columns detected in the uploaded file.")
            
        columns_str = ",".join(sorted([str(c) for c in columns_list])).lower()
        columns_hash = hashlib.md5(columns_str.encode('utf-8')).hexdigest()
        
        field_map = {}
        cached_schema = SchemaCache.objects.filter(columns_hash=columns_hash).first()
        
        if cached_schema:
            field_map = cached_schema.mapping_data
            print("CACHE HIT! AI BYPASSED! Using instantly mapped schema.")
        else:
            print("CACHE MISS. Sending 5-row sample to Smollm for Schema Mapping...")
            sample_csv = pd.DataFrame(sample_rows).to_csv(index=False)
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
            proxy_url = os.environ.get("OLLAMA_PROXY_URL", "")
            ollama_url = f"{proxy_url.rstrip('/')}/api/generate" if proxy_url else "http://localhost:11434/api/generate"
            payload = {"model": "smollm:latest", "prompt": prompt, "stream": False, "options": {"temperature": 0.1, "num_predict": 500}}

            res = requests.post(ollama_url, json=payload, headers={"bypass-tunnel-reminder": "true", "ngrok-skip-browser-warning": "true"}, timeout=120)
            res.raise_for_status()

            ai_text = res.json().get("response", "")
            ai_text = re.sub(r'<think>.*?</think>', '', ai_text, flags=re.DOTALL).strip()

            try:
                match = re.search(r'\{[^{}]+\}', ai_text)
                if match: field_map = json.loads(match.group(0))
                else: field_map = json.loads(ai_text)
                # Ensure it's exactly the dict we expect
                if isinstance(field_map, dict):
                    SchemaCache.objects.update_or_create(columns_hash=columns_hash, defaults={'mapping_data': field_map})
                    print(f"AI Field Map Cached! {field_map}")
            except Exception as e:
                print("Failed to parse mapping JSON. Fallback to default/none. Error:", e)

        write_status({"status": "processing", "progress": 20, "total": total_rows_est, "extracted_count": 0})
        
        name_col = field_map.get("name")
        desc_col = field_map.get("description")
        price_col = field_map.get("price")
        uom_col = field_map.get("unit_of_measurement")
        cat_col = field_map.get("category")
        
        def row_generator():
            if file_extension == 'csv':
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    reader = csv.DictReader(f)
                    for r in reader: yield r
            else:
                for r in df.to_dict('records'): yield r

        products_to_create = []
        extracted_count = 0
        
        for i, row in enumerate(row_generator()):
            def get_val(col_name, default=""):
                val = row.get(col_name) if col_name else None
                return val if val is not None and not pd.isna(val) else default

            raw_name = str(get_val(name_col, "")).strip()
            if not raw_name or raw_name.lower() in ['unnamed', 'unknown', 'null']:
                name_val = f"Unnamed Product {uuid.uuid4().hex[:6]}"
            else: name_val = raw_name[:250]
                
            try:
                price_raw = str(get_val(price_col, "0"))
                price_raw = price_raw.replace('₹', '').replace('$', '').replace(',', '').strip()
                price_val = float(price_raw) if price_raw else 0.0
            except: price_val = 0.0

            desc_val = str(get_val(desc_col, ""))
            if desc_val == 'None' or desc_val.lower() == 'null': desc_val = ""
            uom_val = str(get_val(uom_col, "unit"))
            if uom_val == 'None' or uom_val.lower() == 'null': uom_val = "unit"
            cat_val = str(get_val(cat_col, "Uncategorized"))
            if cat_val == 'None' or cat_val.lower() == 'null': cat_val = "Uncategorized"

            products_to_create.append(
                Product(name=name_val, description=desc_val[:1000], unit_of_measurement=uom_val[:50], price=price_val, category=cat_val[:200])
            )
            extracted_count += 1
            
            # Streaming save (every 500 rows) - Extremely memory efficient
            if len(products_to_create) >= 500:
                connection.close() 
                Product.objects.bulk_create(products_to_create, batch_size=500, ignore_conflicts=True)
                products_to_create.clear()
                
                percent = min(95, 20 + round((extracted_count / total_rows_est) * 75)) if total_rows_est > 0 else 50
                write_status({"status": "processing", "progress": percent, "total": total_rows_est, "extracted_count": extracted_count})

        # Sweep up any remaining products
        if products_to_create:
            connection.close() 
            Product.objects.bulk_create(products_to_create, ignore_conflicts=True)

        write_status({"status": "completed", "progress": 100, "total": total_rows_est, "extracted_count": extracted_count})
        print(f"=== UPLOAD COMPLETE: {extracted_count} products saved! ===")
        
        try: os.remove(file_path)
        except: pass

    except Exception as e:
        import traceback
        traceback.print_exc()
        write_status({"status": "error", "error": f"Fatal Crash: {str(e)}"})
        print(f"Fatal crash inside worker: {e}")


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
            file_extension = file_obj.name.lower().split('.')[-1]
            if file_extension not in ['csv', 'xlsx', 'xls', 'json']:
                 return Response({"error": "Unsupported file format."}, status=status.HTTP_400_BAD_REQUEST)

            import threading
            import uuid
            
            # Avoid resetting if already running
            curr_status = get_status()
            if curr_status.get("status") == "processing":
                 return Response({"error": "An extraction is already running. Please wait."}, status=status.HTTP_409_CONFLICT)
                 
            # Stream the uploaded memory file chunks safely to disk to protect RAM
            temp_path = f"/tmp/etl_upload_{uuid.uuid4().hex}.{file_extension}"
            with open(temp_path, 'wb+') as dest:
                for chunk in file_obj.chunks():
                    dest.write(chunk)
                    
            write_status({"status": "processing", "progress": 0, "total": "Starting...", "extracted_count": 0})
            
            thread = threading.Thread(target=process_file_background, args=(temp_path, file_extension))
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
