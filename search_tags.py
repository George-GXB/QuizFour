with open('C:/Repos/QuizFour/app.py', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if 'multiselect' in line or 'expander' in line or 'タグ' in line:
        print(f'{i}: {line}', end='')

