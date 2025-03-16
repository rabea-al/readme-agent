# Xircuits README Agent

## Overview

The **Xircuits README Agent** is an automated tool designed to generate a complete, professional README file for any Xircuits component library. The agent combines several tools to:
  
1. Extract detailed category information 
2. Retrieve information and capture screenshots for components 
3. Fetch a README template from a GitHub raw URL.
4. Use an OpenAI GPT-powered generator to create a new README in Markdown format that follows the style of the fetched template—concise, clear, and natural.


## Prerequisites

Before running the README Agent, ensure the following:

### Required Software & Libraries

- Python 3.9+
- Xircuits 
- Agent Component Library

Install the required Python dependencies with:
```bash
pip install -r requirements.txt
```

### Environment Variables

- Ensure you have a `.env` file containing the (`OPENAI_API_KEY`).

## How to Run the Agent

1. **Configure the Secret URL:**  
   Provide the secret Xircuits URL (e.g., `http://localhost:8888/lab?token=YOUR_SECRET_TOKEN`) and the target library (category) name as inputs.

2. **Start the Agent:**  
   Run the agent using:
   ```bash
   python readme_agent.py
   ```
   The agent will perform the following steps automatically:
   - Open a Playwright browser and navigate to the secret URL.
   - Use the **extract_category_info** tool to extract complete information about the target category.
   - Use the **extract_component_info** tool to retrieve details for the first and second components in the category.
   - Use the **take_screenshot** tool to capture screenshots for these components and save them as `<ComponentName>.png`.
   - Use the **readme_fetcher** tool to fetch a README template from a specified GitHub raw URL.
   - Use the **readme_generator_from_category** tool (powered by GPT) to generate a new README based on the extracted category details, template, and screenshot links.
   - Finally, the new README is saved as `README.md` in the agent's working directory.


## Usage Example

**User Request:**  
> Please create a README file for the SENDGRID library from the secret link:  
> `http://localhost:8888/lab?token=YOUR_SECRET_TOKEN`

**Agent Process:**  
1. Extracts category information for "SENDGRID".
2. Retrieves details for the first component (`SendGridSendEmail`) and captures its screenshot.
3. Retrieves details for the second component (`SendgridParseExtractEmail`) and captures its screenshot.
4. Fetches the README template from a GitHub raw URL.
5. Generates a new README using the extracted data.
6. Uploads the `README.md` to GitHub.
7. Inserts the screenshots in their appropriate sections within the README file.


