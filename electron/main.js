const { app, BrowserWindow } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const process = require('process')
let mainWindow
let flaskProcess

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: true
    },
    icon: path.join(__dirname, 'icon.ico')
  })

  // Wait for Flask server to start
  setTimeout(() => {
    mainWindow.loadURL('http://localhost:5000')
    mainWindow.setTitle('SmartExaM')
  }, 3000)

  mainWindow.on('closed', function () {
    mainWindow = null
  })
}

function startFlaskServer() {
  let pythonPath
  let scriptPath
  
  if (app.isPackaged) {
    pythonPath = path.join(process.resourcesPath, 'flask', 'python', 'python.exe')
    scriptPath = path.join(process.resourcesPath, 'flask', 'app.py')
  } else {
    pythonPath = 'python'
    scriptPath = path.join(__dirname, '..', 'app.py')
  }

  flaskProcess = spawn(pythonPath, [scriptPath])
  
  flaskProcess.stdout.on('data', (data) => {
    console.log(`Flask stdout: ${data}`)
  })
  
  flaskProcess.stderr.on('data', (data) => {
    console.error(`Flask stderr: ${data}`)
  })
}

app.on('ready', () => {
  startFlaskServer()
  createWindow()
})

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') {
    if (flaskProcess) {
      flaskProcess.kill()
    }
    app.quit()
  }
})

app.on('activate', function () {
  if (mainWindow === null) {
    createWindow()
  }
})
