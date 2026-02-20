#!/usr/bin/env python3
"""
Fix miscategorized principles and applications in article frontmatter.

1. Move application-level values that ended up in principles back to applications
2. Map rogue/invented application values to approved values from the schema
3. Remove pure-theological categories that don't fit the religious liberty taxonomy
"""

import os
import re
import yaml

BASE = "/Users/apl/Documents/PUBLICAR/APL/English/American Sentinel (Religious Freedom)/0. American Sentinel/2. Transcribed"

# The 7 approved principles
APPROVED_PRINCIPLES = {
    "Religious Liberty",
    "Church and State",
    "Limits of Civil Authority",
    "Persecution",
    "Constitutional Principles",
    "Religion and Education",
    "The Sabbath Question",
}

# Values that agents put in principles but are actually applications
# Map: wrong principle → (correct principle to add, application value)
PRINCIPLE_TO_APPLICATION = {
    "Religious Institutions and Civil Power": ("Church and State", "Religious Institutions and Civil Power"),
    "Christian Nation Claims": ("Church and State", "Christian Nation Claims"),
    "Separation of Church and State": ("Church and State", "Separation of Church and State"),
    "Historical Parallels": ("Persecution", "Historical Parallels"),
    "Equal Protection": ("Persecution", "Equal Protection"),
    "Voluntary vs Coerced Religion": ("Religious Liberty", "Voluntary vs Coerced Religion"),
}

# Rogue application values → correct approved application
APPLICATION_MAPPING = {
    # Near-duplicates and word-order variants
    "Civil vs Religious Law": "Religious vs Civil Law",
    "Religious vs Civil Arguments": "Civil vs Religious Arguments",

    # Principles used as applications
    "Church and State": "Separation of Church and State",
    "Limits of Civil Authority": "Proper Role of Government",
    "Religion and Education": "State Schools and Religious Instruction",
    "Religious Liberty": "Freedom of Conscience",
    "Persecution": "Legal Persecution",

    # Sunday law variants
    "Sunday Laws": "Sunday Legislation",
    "Sunday Law Enforcement": "Sunday Legislation",

    # Church power variants → single approved value
    "Church Power and Authority": "Religious Institutions and Civil Power",
    "Papal Authority": "Religious Institutions and Civil Power",
    "Church Politics": "Religious Institutions and Civil Power",
    "Clerical Control of Government": "Religious Institutions and Civil Power",
    "Church Domination": "Religious Institutions and Civil Power",
    "Catholic Church Authority": "Religious Institutions and Civil Power",
    "Papal Political Influence": "Religious Institutions and Civil Power",
    "Papal Infallibility": "Religious Institutions and Civil Power",
    "Religious Authority": "Religious Institutions and Civil Power",
    "Religious Political Influence": "Religious Institutions and Civil Power",

    # Church-state variants
    "Church-State Relations": "Separation of Church and State",

    # Religious tests
    "Religious Tests": "No Religious Tests",

    # Education variants
    "Religious Instruction in Schools": "State Schools and Religious Instruction",
    "Secular Education": "State Schools and Religious Instruction",
    "Religion in Education": "State Schools and Religious Instruction",
    "Parochial Schools": "Sectarian Education",

    # Legislation variants
    "Class Legislation": "Religious Legislation",
    "Legislative Propriety": "Religious Legislation",

    # Liberty/conscience variants
    "Freedom of Religion": "Freedom of Conscience",
    "Freedom of Thought": "Freedom of Conscience",
    "Natural Rights": "Rights of Conscience",

    # Persecution variants
    "Persecution For Conscience' Sake": "Legal Persecution",
    "Police Brutality": "Legal Persecution",

    # Misc → best fit
    "Prohibition": "Legislating Morality",
    "Workers' Rights": "Day of Rest / Labor Arguments",
    "Government Role": "Proper Role of Government",
    "Seventh-day Sabbath Keepers": "Sabbath Observance and Enforcement",
    "Seventh-day Sabbath": "Sabbath Observance and Enforcement",
    "Prophecy and Current Events": "Historical Parallels",
    "Christianity and War": "Proper Role of Government",
    "National Reform Association": "Christian Nation Claims",
    "Christian Citizenship": "Christian Nation Claims",
    "Catholic Doctrine vs. Biblical Faith": "Religious Intolerance",
}

# Pure theological categories to remove (don't fit religious liberty taxonomy)
REMOVE_APPLICATIONS = {
    "Justification by Faith",
    "Faith and Works",
    "Biblical Authority",
    "Missionary Work",
}


def fix_file(filepath):
    """Fix categories in a single article file. Returns (changed, details)."""
    with open(filepath, 'r') as f:
        content = f.read()

    if not content.startswith('---'):
        return False, None

    end = content.find('---', 3)
    if end == -1:
        return False, None

    fm_text = content[3:end]
    body = content[end:]  # includes the closing ---

    try:
        fm = yaml.safe_load(fm_text)
    except Exception:
        return False, None

    if not fm or not isinstance(fm, dict):
        return False, None

    principles = fm.get('principles', []) or []
    applications = fm.get('applications', []) or []
    changed = False
    details = []

    # Step 1: Fix principles - move application-level values to applications
    new_principles = []
    for p in principles:
        if p in PRINCIPLE_TO_APPLICATION:
            correct_principle, app_value = PRINCIPLE_TO_APPLICATION[p]
            if correct_principle not in new_principles and correct_principle not in principles:
                new_principles.append(correct_principle)
            if app_value not in applications:
                applications.append(app_value)
            details.append(f"  principle '{p}' → principle '{correct_principle}' + application '{app_value}'")
            changed = True
        elif p in APPROVED_PRINCIPLES:
            new_principles.append(p)
        else:
            # Unknown principle - keep it but flag
            new_principles.append(p)
            details.append(f"  WARNING: unknown principle '{p}'")

    # Deduplicate principles while preserving order
    seen = set()
    deduped_principles = []
    for p in new_principles:
        if p not in seen:
            seen.add(p)
            deduped_principles.append(p)
    new_principles = deduped_principles

    # Step 2: Fix applications - map rogue values to approved values
    new_applications = []
    for a in applications:
        if a in REMOVE_APPLICATIONS:
            details.append(f"  removed application '{a}'")
            changed = True
            continue
        if a in APPLICATION_MAPPING:
            mapped = APPLICATION_MAPPING[a]
            if mapped not in new_applications:
                new_applications.append(mapped)
            details.append(f"  application '{a}' → '{mapped}'")
            changed = True
        else:
            if a not in new_applications:
                new_applications.append(a)

    if not changed:
        return False, None

    # Rebuild frontmatter
    fm['principles'] = new_principles if new_principles else None
    fm['applications'] = new_applications if new_applications else None

    # Clean up None values
    if fm.get('principles') is None:
        fm.pop('principles', None)
    if fm.get('applications') is None:
        fm.pop('applications', None)

    # Serialize frontmatter preserving field order
    # Use a custom approach to maintain consistent formatting
    new_fm = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False, width=200)
    new_content = '---\n' + new_fm + body

    with open(filepath, 'w') as f:
        f.write(new_content)

    return True, details


def main():
    total_files = 0
    changed_files = 0
    all_details = []

    for year in sorted(os.listdir(BASE)):
        year_dir = os.path.join(BASE, year)
        if not os.path.isdir(year_dir):
            continue
        for issue in sorted(os.listdir(year_dir)):
            issue_dir = os.path.join(year_dir, issue)
            if not os.path.isdir(issue_dir) or issue == 'ocr':
                continue
            for fname in sorted(os.listdir(issue_dir)):
                if not fname.endswith('.md') or fname in ('00_masthead.md', 'uncertainties.md'):
                    continue
                filepath = os.path.join(issue_dir, fname)
                total_files += 1
                was_changed, details = fix_file(filepath)
                if was_changed:
                    changed_files += 1
                    all_details.append((filepath, details))

    print(f"Scanned {total_files} article files")
    print(f"Fixed {changed_files} files")
    print()

    if changed_files <= 100:
        for filepath, details in all_details:
            short = filepath.replace(BASE + '/', '')
            print(f"{short}:")
            for d in details:
                print(d)
    else:
        # Just show summary
        print(f"(Too many to list individually - showing first 30)")
        for filepath, details in all_details[:30]:
            short = filepath.replace(BASE + '/', '')
            print(f"{short}:")
            for d in details:
                print(d)
        print(f"... and {changed_files - 30} more files")


if __name__ == '__main__':
    main()
