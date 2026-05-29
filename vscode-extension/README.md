# LogAnalyzer VS Code Extension

Analyze application logs and build a persistent troubleshooting knowledge graph directly from your editor.

## Features

* **Dashboard Webview**: View the full LogAnalyzer graph and uploaded history directly inside an editor tab.
* **Auto-managed Python Server**: Automatically starts your local FastAPI backend inside your workspace's virtual environment (`venv`) on activation.
* **Context Menu Integration**: Right-click any log or text file in the Explorer sidebar or editor context menu, click **"LogAnalyzer: Analyze Log File"**, and immediately see the AI root-cause analysis!
* **Status Bar Health Checker**: Monitor the status of your local backend server in real-time.

---

## Getting Started / Development Installation

To install and run the extension locally:

### Option A: Run via VS Code Extension Host (Recommended for testing)

1. Open the parent workspace folder in VS Code.
2. Open **[vscode-extension/extension.js](file:///d:/LogAnalyzer/vscode-extension/extension.js)** in your editor.
3. Press **`F5`** (or go to Run and Debug -> **Extension**) to start a new Extension Development Host window.
4. In the new window, open any workspace with log files. The extension will activate and launch the Python server automatically!

### Option B: Sideload into VS Code

1. Copy the folder `vscode-extension` directly into your VS Code extensions folder:
   * **Windows**: `%USERPROFILE%\.vscode\extensions\loganalyzer-agent`
   * **macOS / Linux**: `~/.vscode/extensions/loganalyzer-agent`
2. Restart VS Code. The extension will be fully loaded.

---

## Packaging & Publishing the Extension

To package the extension into a `.vsix` bundle and publish it to the Marketplace:

### 1. Set a Valid Publisher Name
Open `package.json` and replace `"publisher": "local"` with your registered VS Code Marketplace Publisher ID:
```json
"publisher": "your-publisher-id"
```

### 2. Package into a `.vsix` file (Offline Installer)
Open a command prompt in the `vscode-extension/` directory and run:
```cmd
npm run package
```
This command compiles and packages the extension into a file named `loganalyzer-agent-1.0.0.vsix` in the directory root. You can install this `.vsix` file manually on any computer:
* VS Code menu -> **Extensions** -> Click **...** (top right) -> **Install from VSIX...**

### 3. Publish to the Marketplace
1. Make sure you have a publisher registered on the [VS Code Marketplace Portal](https://marketplace.visualstudio.com/manage).
2. Create a **Personal Access Token (PAT)** in Azure DevOps with the scope set to **Marketplace (Publish)**.
3. Log in to your publisher account from your terminal:
   ```cmd
   npx @vscode/vsce login your-publisher-id
   ```
   Paste your Azure DevOps PAT when prompted.
4. Publish the extension directly to the Marketplace:
   ```cmd
   npx @vscode/vsce publish
   ```

---

## Troubleshooting

* If the extension fails to connect, make sure your local **Ollama** app is running (`ollama list` should work in your command prompt).
* Output logs of the Python server are streamed to the VS Code Output Channel: Select **Output** in the bottom panel and choose **LogAnalyzer Agent** from the dropdown.
