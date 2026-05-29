from local_db import DATA_DIR, kv_get, kv_set
from student_store import get_student, list_students, save_student

print(f"Data directory: {DATA_DIR}")

kv_set("test", "hello", ttl_seconds=60)
print("kv test:", kv_get("test"))
print("students:", len(list_students()))
