from pathlib import Path

def clear_all_logs(dir_path: str = "logs"):
    log_dir = Path(dir_path)
    log_files = list(log_dir.glob("*.log"))
    if not log_files:
        print(f"No log files found in '{dir_path}'.")
        return
    
    for log_file in log_files:
        try:
            log_file.write_text("") 
            print(f"Cleared: {log_file.name}")
        except Exception as e:
            print(f"Error clearing {log_file}: {e}")
    
    log_dir = Path("logs\\prompts")
    log_files = list(log_dir.glob("*.log"))
    for log_file in log_files:
        try:
            log_file.write_text("")
            print(f"Cleared: {log_file.name}")
        except Exception as e:
            print(f"Error clearing {log_file}: {e}")

if __name__ == "__main__":
    clear_all_logs()