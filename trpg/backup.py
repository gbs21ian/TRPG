import os
import shutil
import datetime

def create_backup():
    # 현재 날짜와 시간을 포맷팅 (예: 20240521_143000)
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 백업 폴더 이름
    backup_dir = "backups"
    
    # 백업 폴더가 없으면 생성
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        print(f"Created backup directory: {backup_dir}")
    
    # 압축할 파일/폴더 목록 (현재 디렉토리의 모든 파일 포함, backups 폴더 및 숨김 폴더 제외)
    # 여기서는 간단하게 전체 프로젝트 폴더를 압축하되, backups 폴더 자체는 제외합니다.
    
    project_dir = os.getcwd()
    archive_name = os.path.join(backup_dir, f"trpg_backup_{now}")
    
    # 임시 폴더에 백업할 파일들을 복사 (재귀적 복사 문제 방지)
    temp_dir = os.path.join(backup_dir, "temp_backup")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    
    try:
        # 파일 복사
        for item in os.listdir(project_dir):
            # 백업 폴더, .git 등 제외할 항목
            if item == "backups" or item.startswith(".") or item == "__pycache__":
                continue
            
            src = os.path.join(project_dir, item)
            dst = os.path.join(temp_dir, item)
            
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        
        # zip 파일 생성
        shutil.make_archive(archive_name, 'zip', temp_dir)
        print(f"Backup created successfully: {archive_name}.zip")
        
    except Exception as e:
        print(f"Backup failed: {e}")
    finally:
        # 임시 폴더 삭제
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

if __name__ == "__main__":
    create_backup()
