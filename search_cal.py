with open('C:/Repos/QuizFour/app.py', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if 'calendar' in line.lower() or 'cal_opt' in line or 'streamlit_calendar' in line or 'calendar_events' in line:
        print(f'{i}: {line}', end='')

