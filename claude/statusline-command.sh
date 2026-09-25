#!/bin/bash

# Read JSON input from stdin
input=$(cat)

# Extract data from JSON
cwd=$(echo "$input" | jq -r '.workspace.current_dir')
model=$(echo "$input" | jq -r '.model.display_name')
context_remaining=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')

# Get relative path from home if possible
if [[ "$cwd" == "$HOME"* ]]; then
  cwd_display="~${cwd#$HOME}"
else
  cwd_display="$cwd"
fi

# Get git branch and status
git_info=""
if git -C "$cwd" rev-parse --git-dir > /dev/null 2>&1; then
  branch=$(git -C "$cwd" --no-optional-locks branch --show-current 2>/dev/null)

  # Check for changes (use status --porcelain to avoid index lock conflicts)
  if [ -n "$(git -C "$cwd" --no-optional-locks status --porcelain 2>/dev/null)" ]; then
    status="*"
  else
    status=""
  fi

  # Check if behind remote
  behind=""
  upstream=$(git -C "$cwd" --no-optional-locks rev-parse --abbrev-ref @{u} 2>/dev/null)
  if [ -n "$upstream" ]; then
    local_commit=$(git -C "$cwd" --no-optional-locks rev-parse HEAD 2>/dev/null)
    remote_commit=$(git -C "$cwd" --no-optional-locks rev-parse @{u} 2>/dev/null)
    if [ "$local_commit" != "$remote_commit" ]; then
      behind_count=$(git -C "$cwd" --no-optional-locks rev-list --count HEAD..@{u} 2>/dev/null || echo "0")
      if [ "$behind_count" -gt 0 ]; then
        behind=" ⇣"
      fi
    fi
  fi

  git_info=" $branch$status$behind"
fi

# Build status line without emojis
status_line="$cwd_display$git_info"

# Add context info if available
context_window_size=$(echo "$input" | jq -r '.context_window.context_window_size // empty')
total_input=$(echo "$input" | jq -r '.context_window.total_input_tokens // empty')
total_output=$(echo "$input" | jq -r '.context_window.total_output_tokens // empty')

if [ -n "$context_window_size" ] && [ -n "$total_input" ] && [ -n "$total_output" ]; then
  # Calculate used and remaining tokens
  used_tokens=$((total_input + total_output))
  remaining_tokens=$((context_window_size - used_tokens))

  # Format with K suffix for readability
  context_size_k=$((context_window_size / 1000))
  remaining_k=$((remaining_tokens / 1000))

  context_display=$(printf "%.0f" "$context_remaining")
  status_line="$status_line | Context: ${remaining_k}K/${context_size_k}K (${context_display}%)"
fi

# Print the status line
printf "%s" "$status_line"
