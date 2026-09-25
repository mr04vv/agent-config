---
description: "Analyze changes, create granular commits, push to GitHub, and create a pull request"
allowed-tools: ["Bash"]
---

## Push and Create Pull Request

差分をコミットしてPRを作成してくれる

## Overview

This command analyzes current changes, creates appropriately granular commits, pushes to GitHub, and creates a Pull Request.

## Execution Steps

1. **Review and analyze changes**
   - Check untracked and modified files with `git status`
   - Analyze changes in detail with `git diff`
   - Review recent commit message style with `git log`

2. **Logical separation of changes**
   - Categorize into feature additions, bug fixes, refactoring, tests, documentation, etc.
   - Group related changes together
   - Plan individual commits for each group

3. **Create commits**
   - Stage and commit each logical unit separately
   - Write clear and concise commit messages
   - Focus commit messages on "why" rather than "what"

4. **Push to remote**
   - Push current branch to remote
   - Create new branch if necessary

5. **Create Pull Request**
   - Use `gh pr create` to create PR
   - Include summary of changes and impact
   - Document testing approach

## Commit Granularity Guidelines

- **One commit, one purpose**: Each commit should contain only one logical change
- **Independence**: Each commit should be buildable on its own
- **Separation examples**:
  - New feature and its tests in separate commits
  - Refactoring and functional changes in separate commits
  - Documentation updates as independent commits

## Changeset Support

For projects using changesets (e.g., with `@changesets/cli`):

1. **Check for changeset requirement**
   - Look for `.changeset` directory in the project root
   - Check if `package.json` includes changeset scripts

2. **Create changeset if needed**
   - Run `npx changeset` or `yarn changeset` before creating the PR
   - Select the version bump from the diff (patch/minor); ask the user before choosing major
   - Write a clear changeset description
   - Include the generated changeset file in the commit

3. **Changeset commit**
   - Create a separate commit for the changeset
   - Use commit message like: "chore: add changeset for [feature/fix]"

## Important Notes

- Include pre-commit hook changes if applicable
- Verify no sensitive information (API keys, passwords, etc.) is included
- Ensure lint and type checks pass before committing
- For monorepo projects with changesets, ensure all affected packages are included