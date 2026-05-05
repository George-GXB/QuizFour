with open('C:/Repos/QuizFour/app.py', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if line.startswith('def render_') or line.startswith('def _render_'):
        print(f'{i}: {line}', end='')

