with open('C:/Repos/QuizFour/app.py', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if 'screen' in line.lower() or 'page' in line.lower() or 'ログイン' in line or 'login' in line.lower() or 'session_state' in line and ('screen' in line or 'page' in line):
        print(f'{i}: {line}', end='')

