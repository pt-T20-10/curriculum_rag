# test_planner.py
from src.agents.planner import HybridPlanner
from src.log_config import setup_logger

# Setup log để nhìn thấy output
setup_logger()

# Giả lập state đầu vào
mock_state = {
    "request": "Teach me basic Python for Data Science",
    "messages": []
}

# Chạy thử hàm
result = plan_curriculum(mock_state) # type: ignore

# Kiểm tra kết quả
if result.get("curriculum"):
    print("\n✅ SUCCESS! Plan created.")
    print(result["curriculum"].topic) #type: ignore
    print(result["curriculum"].chapters) #type: ignore
else:
    print("\n❌ FAILED!")
    print(result.get("messages"))