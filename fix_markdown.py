#!/usr/bin/env python3
"""Fix markdown linting issues in REDIS_ARCHITECTURE_REVIEW.md"""

import re

def fix_markdown(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    fixed_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Get previous and next lines safely
        prev_line = lines[i-1] if i > 0 else '\n'
        next_line = lines[i+1] if i < len(lines) - 1 else '\n'

        # Fix code blocks without language
        if line.startswith('```') and line.strip() == '```':
            # Check if it's a closing fence
            if i > 0:
                # Look backward for opening fence
                is_closing = False
                for j in range(i-1, -1, -1):
                    if lines[j].startswith('```'):
                        if lines[j].strip() == '```' or re.match(r'^```\w+', lines[j]):
                            is_closing = True
                            break

                if not is_closing:
                    # This is an opening fence without language - add 'text'
                    line = '```text\n'

        # MD031: Add blank line before code fence if missing
        if line.startswith('```'):
            if prev_line.strip() and not prev_line.startswith('```'):
                fixed_lines.append('\n')

        # MD032: Add blank line before list if missing
        if re.match(r'^[\-\*\+]\s', line) or re.match(r'^\d+\.\s', line):
            if prev_line.strip() and not prev_line.startswith(('#', '-', '*', '+')) and not re.match(r'^\d+\.\s', prev_line):
                if not prev_line.strip() == '':
                    fixed_lines.append('\n')

        fixed_lines.append(line)

        # MD031: Add blank line after code fence if missing
        if line.startswith('```') and not line.strip().endswith('```'):
            # This is a closing fence
            if i > 0 and '```' in ''.join(lines[max(0, i-20):i]):
                if next_line.strip() and not next_line.startswith('#'):
                    if i < len(lines) - 1:
                        if not next_line.strip() == '':
                            fixed_lines.append('\n')

        # MD032: Add blank line after list if missing
        if (re.match(r'^[\-\*\+]\s', line) or re.match(r'^\d+\.\s', line)):
            if next_line.strip() and not next_line.startswith(('#', '-', '*', '+', ' ', '\t')) and not re.match(r'^\d+\.\s', next_line):
                if i < len(lines) - 1:
                    if not next_line.strip() == '':
                        fixed_lines.append('\n')

        i += 1

    # MD012: Remove multiple consecutive blank lines
    final_lines = []
    blank_count = 0
    for line in fixed_lines:
        if line.strip() == '':
            blank_count += 1
            if blank_count <= 1:
                final_lines.append(line)
        else:
            blank_count = 0
            final_lines.append(line)

    # Fix ordered list numbering (MD029)
    in_list = False
    list_counter = 0
    result_lines = []

    for line in final_lines:
        if re.match(r'^\d+\.\s', line):
            if not in_list:
                in_list = True
                list_counter = 1
            else:
                list_counter += 1

            # Replace the number
            line = re.sub(r'^\d+\.', f'{list_counter}.', line)
        elif line.strip() == '' or not line.startswith(' '):
            # Reset list counter on blank line or non-indented line
            if in_list and line.strip() == '':
                in_list = False
                list_counter = 0

        result_lines.append(line)

    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(result_lines)

    print(f"Fixed {filepath}")

if __name__ == '__main__':
    fix_markdown('REDIS_ARCHITECTURE_REVIEW.md')
