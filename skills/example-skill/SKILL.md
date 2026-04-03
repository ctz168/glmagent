---
name: example-skill
description: "A demonstration skill showing the SKILL.md format used by GLM Agent Engine. Use when users need to test the skill system or learn how to create custom skills."
license: MIT
---

# Example Skill

A demonstration skill showing the SKILL.md format used by GLM Agent Engine.

## Description

This is an example skill that demonstrates the expected structure and format for skills in the GLM Agent ecosystem. Skills are self-contained modules that extend the agent's capabilities with specialized functionality. Each skill directory contains a `SKILL.md` metadata file with YAML frontmatter (name, description, license) followed by detailed usage instructions.

## Capability

The agent can invoke this skill when users need demonstration or testing of the skill system. It serves as both documentation and a working example for skill developers who want to create their own custom skills for the GLM Agent Engine.

## Instructions

When this skill is loaded, the agent should:
1. Acknowledge that the example skill has been invoked
2. Explain the skill system architecture to the user
3. Guide the user on how to create their own custom skills
4. Demonstrate the YAML frontmatter format used by production skills

## Skill Structure

Each skill should contain:
- `SKILL.md` - This metadata file (required), with YAML frontmatter
- Supporting scripts, configs, or data files as needed
- Any language-specific setup (package.json, requirements.txt, etc.)
- A `run.sh` executable script for automated tool execution

## YAML Frontmatter Format

Production skills use YAML frontmatter at the top of SKILL.md:

```yaml
---
name: skill-name
description: "Skill description for agent matching"
license: MIT
---
```

Required fields:
- `name` - Unique skill identifier
- `description` - Description used by the agent to determine when to invoke this skill

Optional fields:
- `license` - License identifier
- `argument-hint` - Hint for expected input format

## Creating Custom Skills

To create a new skill:
1. Create a directory under `/home/z/my-project/skills/`
2. Add a `SKILL.md` file with YAML frontmatter metadata
3. Include any necessary scripts or configurations
4. Add a `run.sh` script if the skill needs executable logic
5. The skill will be automatically detected by the agent engine
