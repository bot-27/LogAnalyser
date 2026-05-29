const vscode = require('vscode');
const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

let backendProcess = null;
let outputChannel = null;
let statusBarItem = null;
let activePanel = null;

// Helper to check if the server is healthy
function checkServerHealth(port) {
    return new Promise((resolve) => {
        const options = {
            hostname: '127.0.0.1',
            port: port,
            path: '/health',
            method: 'GET',
            timeout: 1000
        };

        const req = http.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                if (res.statusCode === 200) {
                    try {
                        const json = JSON.parse(data);
                        resolve({ online: true, ours: json.default_model !== undefined });
                    } catch (e) {
                        resolve({ online: true, ours: false });
                    }
                } else {
                    resolve({ online: false, ours: false });
                }
            });
        });

        req.on('error', () => {
            resolve({ online: false, ours: false });
        });

        req.on('timeout', () => {
            req.destroy();
            resolve({ online: false, ours: false });
        });

        req.end();
    });
}

function updateStatusBar(online, state) {
    if (!statusBarItem) return;
    if (online) {
        statusBarItem.text = '$(check) LogAnalyzer';
        statusBarItem.tooltip = 'LogAnalyzer Agent is online and running.';
        statusBarItem.command = 'loganalyzer.showDashboard';
        statusBarItem.show();
    } else {
        if (state === 'starting') {
            statusBarItem.text = '$(sync~spin) LogAnalyzer (Starting)';
            statusBarItem.tooltip = 'Starting local FastAPI server...';
        } else if (state === 'error') {
            statusBarItem.text = '$(error) LogAnalyzer (Error)';
            statusBarItem.tooltip = 'Failed to start LogAnalyzer backend.';
        } else {
            statusBarItem.text = '$(circle-slash) LogAnalyzer (Offline)';
            statusBarItem.tooltip = 'LogAnalyzer backend is offline.';
        }
        statusBarItem.command = 'loganalyzer.showDashboard';
        statusBarItem.show();
    }
}

async function startBackend(port, workspaceRoot) {
    outputChannel.appendLine(`[INFO] Checking health of port ${port}...`);
    const health = await checkServerHealth(port);
    if (health.online) {
        if (health.ours) {
            outputChannel.appendLine(`[INFO] LogAnalyzer backend already running on port ${port}.`);
            updateStatusBar(true);
            return;
        } else {
            vscode.window.showErrorMessage(`Port ${port} is occupied by another service. Cannot start LogAnalyzer.`);
            updateStatusBar(false, 'error');
            return;
        }
    }

    outputChannel.appendLine(`[INFO] Starting LogAnalyzer backend on port ${port}...`);
    updateStatusBar(false, 'starting');

    // Find Python path
    let pythonPath = 'python'; // default fallback
    const venvPythonWin = path.join(workspaceRoot, 'venv', 'Scripts', 'python.exe');
    const venvPythonUnix = path.join(workspaceRoot, 'venv', 'bin', 'python');

    if (fs.existsSync(venvPythonWin)) {
        pythonPath = venvPythonWin;
        outputChannel.appendLine(`[INFO] Using Windows virtual environment Python: ${pythonPath}`);
    } else if (fs.existsSync(venvPythonUnix)) {
        pythonPath = venvPythonUnix;
        outputChannel.appendLine(`[INFO] Using Unix virtual environment Python: ${pythonPath}`);
    } else {
        outputChannel.appendLine(`[WARNING] Virtual environment not found. Using system Python.`);
    }

    const appPath = path.join(workspaceRoot, 'backend', 'app.py');
    if (!fs.existsSync(appPath)) {
        vscode.window.showErrorMessage(`Backend script not found at ${appPath}`);
        updateStatusBar(false, 'error');
        return;
    }

    try {
        backendProcess = childProcess.spawn(pythonPath, [appPath], {
            cwd: workspaceRoot,
            env: { ...process.env, PORT: String(port) }
        });

        backendProcess.stdout.on('data', (data) => {
            outputChannel.append(data.toString());
        });

        backendProcess.stderr.on('data', (data) => {
            outputChannel.append(data.toString());
        });

        backendProcess.on('close', (code) => {
            outputChannel.appendLine(`[INFO] Backend process exited with code ${code}`);
            backendProcess = null;
            updateStatusBar(false, 'offline');
        });

        // Wait for server to become healthy (check up to 10 times, 500ms intervals)
        for (let i = 0; i < 15; i++) {
            await new Promise(r => setTimeout(r, 600));
            const status = await checkServerHealth(port);
            if (status.online) {
                outputChannel.appendLine(`[INFO] Backend successfully started and responsive.`);
                updateStatusBar(true);
                return;
            }
        }
        outputChannel.appendLine(`[WARNING] Backend started but not responding to health check on port ${port}.`);
    } catch (err) {
        outputChannel.appendLine(`[ERROR] Failed to start backend: ${err.message}`);
        vscode.window.showErrorMessage(`Failed to start LogAnalyzer backend: ${err.message}`);
        updateStatusBar(false, 'error');
    }
}

function createWebviewPanel(port) {
    if (activePanel) {
        activePanel.reveal(vscode.ViewColumn.One);
        return activePanel;
    }

    const panel = vscode.window.createWebviewPanel(
        'loganalyzer',
        'LogAnalyzer Agent',
        vscode.ViewColumn.One,
        {
            enableScripts: true,
            retainContextWhenHidden: true
        }
    );

    activePanel = panel;

    panel.onDidDispose(() => {
        activePanel = null;
    });

    panel.webview.html = getWebviewContent(port);

    return panel;
}

function getWebviewContent(port) {
    return `<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>LogAnalyzer Agent</title>
        <style>
            body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #0a0e1a; }
            iframe { width: 100%; height: 100%; border: none; }
        </style>
    </head>
    <body>
        <iframe src="http://localhost:${port}/"></iframe>
        <script>
            const vscode = acquireVsCodeApi();
            let isLoaded = false;
            
            // Forward messages from VS Code extension to the iframe (e.g. commands to analyze)
            window.addEventListener('message', event => {
                if (event.data && event.data.command === 'ping') {
                    if (isLoaded) {
                        vscode.postMessage({ command: 'ready' });
                    }
                    return;
                }
                const iframe = document.querySelector('iframe');
                if (iframe && iframe.contentWindow) {
                    iframe.contentWindow.postMessage(event.data, '*');
                }
            });

            // Listen to messages from the iframe and forward them to VS Code extension
            window.addEventListener('message', event => {
                if (event.data && event.data.command === 'ready') {
                    isLoaded = true;
                    vscode.postMessage({ command: 'ready' });
                }
            });
        </script>
    </body>
    </html>`;
}

function activate(context) {
    outputChannel = vscode.window.createOutputChannel('LogAnalyzer Agent');
    context.subscriptions.push(outputChannel);

    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    context.subscriptions.push(statusBarItem);

    const port = 8000;
    const workspaceRoot = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0]
        ? vscode.workspace.workspaceFolders[0].uri.fsPath
        : '';

    if (workspaceRoot) {
        startBackend(port, workspaceRoot);
    } else {
        outputChannel.appendLine('[WARNING] No open folder found in workspace. Backend auto-start skipped.');
    }

    // Command: Show Dashboard
    let showDashboardCmd = vscode.commands.registerCommand('loganalyzer.showDashboard', () => {
        createWebviewPanel(port);
    });
    context.subscriptions.push(showDashboardCmd);

    // Command: Analyze File (supports multiple selected files)
    let analyzeFileCmd = vscode.commands.registerCommand('loganalyzer.analyzeFile', async (uri, uris) => {
        let filePaths = [];
        if (uris && uris.length > 0) {
            filePaths = uris.map(u => u.fsPath);
        } else if (uri && uri.fsPath) {
            filePaths = [uri.fsPath];
        } else {
            const activeEditor = vscode.window.activeTextEditor;
            if (activeEditor) {
                filePaths = [activeEditor.document.uri.fsPath];
            }
        }

        if (filePaths.length === 0) {
            vscode.window.showErrorMessage('No log file selected for analysis.');
            return;
        }

        try {
            const filesData = [];
            for (const fp of filePaths) {
                if (fs.existsSync(fp) && fs.statSync(fp).isFile()) {
                    const content = fs.readFileSync(fp, 'utf8');
                    filesData.push({
                        name: path.basename(fp),
                        text: content
                    });
                }
            }

            if (filesData.length === 0) {
                vscode.window.showErrorMessage('No valid files to analyze.');
                return;
            }

            outputChannel.appendLine(`[INFO] Analyzing ${filesData.length} file(s)...`);

            // Ensure server is online
            const health = await checkServerHealth(port);
            if (!health.online) {
                if (workspaceRoot) {
                    await startBackend(port, workspaceRoot);
                } else {
                    vscode.window.showErrorMessage('LogAnalyzer backend is offline and workspace folder is missing.');
                    return;
                }
            }

            const panel = createWebviewPanel(port);
            
            let messageToSend;
            if (filesData.length === 1) {
                messageToSend = { command: 'analyze', text: filesData[0].text, name: filesData[0].name };
            } else {
                messageToSend = { command: 'analyzeBatch', files: filesData };
            }

            // We register the listener to wait for Webview ready signal
            const msgListener = panel.webview.onDidReceiveMessage(msg => {
                if (msg.command === 'ready') {
                    panel.webview.postMessage(messageToSend);
                    msgListener.dispose();
                }
            });

            // Send a ping probe to see if webview is already running and ready
            panel.webview.postMessage({ command: 'ping' });

        } catch (err) {
            vscode.window.showErrorMessage(`Failed to read log files: ${err.message}`);
        }
    });
    context.subscriptions.push(analyzeFileCmd);
}

function deactivate() {
    if (backendProcess) {
        outputChannel.appendLine('[INFO] Stopping backend process...');
        backendProcess.kill();
        backendProcess = null;
    }
}

module.exports = {
    activate,
    deactivate
};
