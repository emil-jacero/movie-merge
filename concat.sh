#!/bin/bash

# Define the list of Python files and the output file
PYTHON_FILES=("main.py" "tools.py") # Add your Python files here
OUTPUT_FILE="output.txt"
SEPARATOR="\n# --- File Separator ---\n" # Define the separator

# Clear the output file if it exists
> "$OUTPUT_FILE"

# Loop through each Python file
for FILE in "${PYTHON_FILES[@]}"; do
  # Append the content of the file to the output file
  cat "$FILE" >> "$OUTPUT_FILE"
  # Append the separator to the output file
  echo -e "$SEPARATOR" >> "$OUTPUT_FILE"
done

echo "Files have been concatenated into $OUTPUT_FILE"
