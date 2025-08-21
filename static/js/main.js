// main_secure.js - auto patched with CSRF support
(function(){
    const socket = io({ transports: ["websocket"], reconnection: true, reconnectionAttempts: 5, reconnectionDelay: 1000 });
    window.socket = socket;
    let csrfToken = null;

    socket.on("csrf_token", (data) => {
        csrfToken = data && data.token;
        console.log("CSRF token received:", csrfToken);
    });

    const _origEmit = socket.emit.bind(socket);
    socket.emit = function(event, ...args){
        if (!csrfToken) {
            console.warn("CSRF token not ready; sending anyway (server will reject if required):", event);
        }
        if (args.length === 0) {
            args = [ { csrf: csrfToken } ];
        } else if (typeof args[0] === "object" && args[0] !== null && !Array.isArray(args[0])) {
            args[0] = Object.assign({}, args[0], { csrf: csrfToken });
        } else {
            args.unshift({ csrf: csrfToken });
        }
        return _origEmit(event, ...args);
    };

    socket.on("terminal_output", (data) => {
        if (data && data.output) {
            const el = document.querySelector("#terminalOutput");
            if (el) { el.value += data.output; el.scrollTop = el.scrollHeight; }
        }
    });

    socket.on("connect_error", (err) => {
        console.error("Socket connect_error:", err && err.message);
    });
})();

// --- Original code below ---
// main.js

const terminalOutput = document.getElementById('terminal-output');
const terminalInput = document.getElementById('terminal-input');
const prompt = '$ ';
const TYPING_SPEED = 10;
let isTyping = false;
let commandHistory = [];
let historyIndex = -1;
const toggleSoundButton = document.getElementById('toggle-sound');
const rebootSystemButton = document.getElementById('reboot-system');
const connectionStatusIndicator = document.getElementById('connection-status');
const systemTimeElement = document.getElementById('system-time');
const uptimeElement = document.getElementById('uptime');
const channelFrequencyElement = document.getElementById('channel-frequency');
const networkPingElement = document.getElementById('network-ping');
const uiBottomPanel = document.getElementById('ui-bottom-panel');
const loadingScreen = document.getElementById('loading-screen');
const mainTerminalContainer = document.getElementById('main-terminal-container');
const initialLoadingBar = document.getElementById('initial-loading-bar');
const alphaFreqLine = document.getElementById('alpha-freq-line');
const betaFreqLine = document.getElementById('beta-freq-line');
const alphaFrequencyElement = document.getElementById('alpha-frequency');
const betaFrequencyElement = document.getElementById('beta-frequency');
let soundEnabled = true;
let uptimeSeconds = 0;
let currentPing = '--';
let pingIntervalId = null;
const socket = io();
const keyPressSounds = [new Audio('/static/audio/key_press_1.mp3'), new Audio('/static/audio/key_press_2.mp3'), new Audio('/static/audio/key_press_3.mp3')];
const enterSounds = [new Audio('/static/audio/enter_1.mp3'), new Audio('/static/audio/enter_2.mp3'), new Audio('/static/audio/enter_3.mp3'), ];
const commandDoneSound = new Audio('/static/audio/command_done.mp3');
const commandPlugins = {};

function playRandomSound(audioArray) {
    if (!soundEnabled || audioArray.length === 0) return;
    const sound = audioArray[Math.floor(Math.random() * audioArray.length)];
    sound.currentTime = 0;
    sound.volume = 0.6;
    sound.play().catch(e => {});
}

function playSingleSound(audioElement) {
    if (!soundEnabled || !audioElement) return;
    audioElement.currentTime = 0;
    audioElement.volume = 0.7;
    audioElement.play().catch(e => {});
}

function registerCommand(name, handler) {
    commandPlugins[name.toLowerCase()] = handler;
}

registerCommand('clear', function() {
    terminalOutput.value = '';
    displayOutput(prompt, false, true);
    playSingleSound(commandDoneSound);
});

function initializeTerminalDisplay() {
    displayOutput("Инициализация Терминала...\nСвязь установлена.\nДоступ ограничен. Введите 'login <UID> <ключ>'\nДля списка команд введите 'help'\n" + prompt, false, true);
    terminalInput.focus();
}

function loadDataFromLocalStorage() {
    try {
        const savedHistory = JSON.parse(localStorage.getItem('stalker_terminal_commandHistory'));
        const savedOutput = localStorage.getItem('stalker_terminal_terminalOutput');
        const savedSound = JSON.parse(localStorage.getItem('stalker_terminal_soundEnabled'));
        if (Array.isArray(savedHistory)) {
            commandHistory = savedHistory;
        }
        if (typeof savedSound === 'boolean') {
            soundEnabled = savedSound;
            if (toggleSoundButton) {
                toggleSoundButton.textContent = `ЗВУК: ${soundEnabled ? 'ВКЛ' : 'ВЫКЛ'}`;
            }
        }
        if (typeof savedOutput === 'string' && savedOutput.trim() !== '') {
            terminalOutput.value = savedOutput;
            terminalOutput.scrollTop = terminalOutput.scrollHeight;
            return true;
        }
    } catch (e) {}
    return false;
}

document.addEventListener('DOMContentLoaded', (event) => {
    let wasOutputLoaded = false;
    wasOutputLoaded = loadDataFromLocalStorage();

    mainTerminalContainer.classList.add('hidden');
    uiBottomPanel.classList.add('hidden');
    loadingScreen.classList.remove('hidden');
    initialLoadingBar.style.width = '0%';

    let progress = 0;
    const loadingInterval = setInterval(() => {
        progress += 10;
        if (progress > 100) progress = 100;
        initialLoadingBar.style.width = `${progress}%`;
        if (progress >= 100) {
            clearInterval(loadingInterval);
            setTimeout(() => {
                loadingScreen.classList.add('hidden');
                mainTerminalContainer.classList.remove('hidden');
                if (wasOutputLoaded) {
                    terminalInput.focus();
                } else {
                    initializeTerminalDisplay();
                }
            }, 300);
        }
    }, 80);

    updateSystemTimeAndUptime();
    setInterval(updateSystemTimeAndUptime, 1000);
    startPingMeasurement();

    if (toggleSoundButton) {
        toggleSoundButton.addEventListener('click', () => {
            soundEnabled = !soundEnabled;
            toggleSoundButton.textContent = `ЗВУК: ${soundEnabled ? 'ВКЛ' : 'ВЫКЛ'}`;
            saveDataToLocalStorage();
        });
    }

    if (rebootSystemButton) {
        rebootSystemButton.addEventListener('click', () => {
            localStorage.removeItem('stalker_terminal_terminalOutput');
            window.location.reload();
        });
    }
});

terminalInput.addEventListener('keydown', function(event) {
    if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) {
        playRandomSound(keyPressSounds);
    }
    if (event.key === 'Enter') {
        event.preventDefault();
        playRandomSound(enterSounds);
        if (!isTyping) {
            processCommand();
        }
    } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (commandHistory.length > 0) {
            if (historyIndex < commandHistory.length - 1) {
                historyIndex++;
            }
            terminalInput.value = commandHistory[historyIndex];
            setTimeout(() => terminalInput.selectionStart = terminalInput.selectionEnd = terminalInput.value.length, 0);
        }
    } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (historyIndex > -1) {
            historyIndex--;
            terminalInput.value = historyIndex === -1 ? '' : commandHistory[historyIndex];
            setTimeout(() => terminalInput.selectionStart = terminalInput.selectionEnd = terminalInput.value.length, 0);
        }
    }
});

socket.on('terminal_output', function(data) {
    if (data.output === "<CLEAR_TERMINAL>\n") {
        terminalOutput.value = '';
        displayOutput(prompt, false, true);
        playSingleSound(commandDoneSound);
        return;
    }
    displayOutput(data.output, true);
    playSingleSound(commandDoneSound);
});

socket.on('update_ui_state', function(data) {
    const role = data.role;
    const showUiPanel = data.show_ui_panel;
    if (uiBottomPanel) {
        uiBottomPanel.classList.toggle('hidden', !showUiPanel);
    }
    if (channelFrequencyElement && data.channel_frequency) {
        channelFrequencyElement.textContent = data.channel_frequency;
    }
    if (role === 'syndicate' && data.squad_frequencies) {
        alphaFrequencyElement.textContent = data.squad_frequencies.alpha || '--.-- МГц';
        betaFrequencyElement.textContent = data.squad_frequencies.beta || '--.-- МГц';
        alphaFreqLine.classList.remove('hidden');
        betaFreqLine.classList.remove('hidden');
        if (channelFrequencyElement) channelFrequencyElement.parentElement.classList.add('hidden');
    } else {
        if (alphaFreqLine) alphaFreqLine.classList.add('hidden');
        if (betaFreqLine) betaFreqLine.classList.add('hidden');
        if (channelFrequencyElement) channelFrequencyElement.parentElement.classList.remove('hidden');
    }
});

socket.on('pong_response', function() {
    currentPing = Date.now() - window.pingStartTime;
    if (networkPingElement) {
        networkPingElement.textContent = `${currentPing}мс`;
    }
});

function startPingMeasurement() {
    if (pingIntervalId) clearInterval(pingIntervalId);
    pingIntervalId = setInterval(() => {
        window.pingStartTime = Date.now();
        socket.emit('ping_check');
    }, 3000);
}

function processCommand() {
    let fullCommand = terminalInput.value.trim();
    if (fullCommand === '') {
        displayOutput(prompt, false, true);
        terminalInput.value = '';
        return;
    }
    if (commandHistory[0] !== fullCommand) {
        commandHistory.unshift(fullCommand);
        saveDataToLocalStorage();
    }
    historyIndex = -1;
    displayOutput(prompt + fullCommand + '\n', false, true);
    const cmdName = fullCommand.split(' ')[0].toLowerCase();
    if (commandPlugins[cmdName]) {
        commandPlugins[cmdName](fullCommand.split(' ').slice(1));
        terminalInput.value = '';
    } else {
        socket.emit('terminal_input', {
            command: fullCommand
        });
        terminalInput.value = '';
    }
}

function displayOutput(text, addNewLine, isInstant = false) {
    if (isTyping && !isInstant) return;
    if (isInstant) {
        terminalOutput.value += text;
        if (addNewLine && !text.endsWith('\n')) {
            terminalOutput.value += '\n';
        }
        terminalOutput.scrollTop = terminalOutput.scrollHeight;
        terminalInput.focus();
        saveDataToLocalStorage();
        return;
    }
    isTyping = true;
    let i = 0;
    function typeChar() {
        if (i < text.length) {
            terminalOutput.value += text.charAt(i++);
            terminalOutput.scrollTop = terminalOutput.scrollHeight;
            setTimeout(typeChar, TYPING_SPEED);
        } else {
            if (addNewLine && !text.endsWith('\n')) {
                terminalOutput.value += '\n';
            }
            isTyping = false;
            displayOutput(prompt, false, true);
            terminalInput.focus();
        }
    }
    typeChar();
}

function updateSystemTimeAndUptime() {
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    if (systemTimeElement) systemTimeElement.textContent = `${hours}:${minutes}:${seconds}`;
    uptimeSeconds++;
    const uptHours = String(Math.floor(uptimeSeconds / 3600)).padStart(2, '0');
    const uptMinutes = String(Math.floor((uptimeSeconds % 3600) / 60)).padStart(2, '0');
    const uptSeconds = String(uptimeSeconds % 60).padStart(2, '0');
    if (uptimeElement) uptimeElement.textContent = `${uptHours}:${uptMinutes}:${uptSeconds}`;
}

function saveDataToLocalStorage() {
    try {
        localStorage.setItem('stalker_terminal_commandHistory', JSON.stringify(commandHistory));
        localStorage.setItem('stalker_terminal_terminalOutput', terminalOutput.value);
        localStorage.setItem('stalker_terminal_soundEnabled', JSON.stringify(soundEnabled));
    } catch (e) {}
}