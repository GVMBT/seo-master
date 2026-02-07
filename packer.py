import zipfile
import os

def create_claude_zip(output_filename='project_for_claude.zip'):
    # Что мы НЕ берем в архив
    exclude_dirs = {'venv', '.git', '__pycache__', '.idea', '.vscode'}
    exclude_files = {'.env', 'project_for_claude.zip'}

    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            # Фильтруем папки
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if file not in exclude_files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, '.'))
                    print(f"Добавлено: {file_path}")

if __name__ == "__main__":
    create_claude_zip()
    print("\n✅ Архив готов! Можешь кидать его в Claude.")
