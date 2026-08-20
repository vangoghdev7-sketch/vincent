import os
import re

def process_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return False

    orig = content

    # 1. Python env var fallbacks
    def py_env_replacer(m):
        var_name = m.group(1)
        return f'os.environ.get("VINCENT_{var_name}", os.environ.get("SHADOWBROKER_{var_name}"'
    
    content = re.sub(r'os\.environ\.get\(\s*["\']VINCENT_([A-Z0-9_]+)["\']', py_env_replacer, content)

    # 2. TypeScript env var fallbacks
    def ts_env_replacer(m):
        var_name = m.group(1)
        return f'(process.env.VINCENT_{var_name} || process.env.SHADOWBROKER_{var_name})'
    
    content = re.sub(r'process\.env\.VINCENT_([A-Z0-9_]+)', ts_env_replacer, content)

    # 3. JS Globals
    content = content.replace('__VINCENT_DESKTOP__', '__VINCENT_DESKTOP__')
    content = content.replace('__VINCENT_LOCAL_CONTROL__', '__VINCENT_LOCAL_CONTROL__')

    # 4. Standard replacements
    replacements = [
        ('Vincent', 'Vincent'),
        ('VINCENT', 'VINCENT'),
        ('vincent', 'vincent'),
        ('Vincent', 'Vincent'),
        ('vincent', 'vincent'),
        ('vincent', 'vincent'),
        ('Vincent Router', 'Vincent Router'),
        ('vincent-router', 'vincent-router'),
        ('Vincent Router', 'Vincent Router'),
        ('VINCENT_ROUTER', 'VINCENT_ROUTER')
    ]

    for old, new in replacements:
        content = content.replace(old, new)

    # 5. Restore Temp
    content = content.replace('SHADOWBROKER', 'VINCENT')

    if content != orig:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False

def main():
    skills_dir = '/home/vangogh/Projeto_Vincent_OSINT/vincent_os/openclaw-skills'
    old_folder = os.path.join(skills_dir, 'vincent')
    new_folder = os.path.join(skills_dir, 'vincent')
    
    symlink_path = os.path.join(skills_dir, 'vincent_os')
    if os.path.islink(symlink_path):
        os.unlink(symlink_path)
        
    if os.path.exists(old_folder):
        os.rename(old_folder, new_folder)
        print(f"Renamed {old_folder} to {new_folder}")
        
    modified_files = []
    for root, dirs, files in os.walk('/home/vangogh/Projeto_Vincent_OSINT/vincent_os'):
        if 'node_modules' in root or '.git' in root or '.next' in root:
            continue
        for file in files:
            filepath = os.path.join(root, file)
            if filepath.endswith(('.png', '.jpg', '.jpeg', '.gif', '.ico', '.pyc', '.map', '.exe', '.gz', '.zip', '.pdf')):
                continue
            
            if process_file(filepath):
                modified_files.append(filepath)
    
    print(f"Modified {len(modified_files)} files:")
    for f in modified_files:
        print(f)

if __name__ == "__main__":
    main()
