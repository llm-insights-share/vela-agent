from routes.skills import _parse_skill_md

raw = """---
name: my-skill
description: A test skill
---

# Overview
This is a test skill.

## Instructions
Do something useful.
"""
manifest, instructions = _parse_skill_md(raw)
print('Test 1 - Standard SKILL.md:')
print('  name:', manifest.get('name'))
print('  description:', manifest.get('description'))
print('  instructions preview:', instructions[:80])
print()

raw2 = """# My Skill

This skill does something.
"""
manifest2, instructions2 = _parse_skill_md(raw2)
print('Test 2 - No frontmatter:')
print('  name:', manifest2.get('name'))
print('  instructions preview:', instructions2[:80])
print()

raw3 = """---
---

# Fallback
Some content here.
"""
manifest3, instructions3 = _parse_skill_md(raw3)
print('Test 3 - Empty frontmatter:')
print('  name:', manifest3.get('name'))
print('  instructions preview:', instructions3[:80])