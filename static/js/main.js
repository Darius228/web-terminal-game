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

const uiBottomPanel = document.getElementById('ui-bottom-panel'); 
const loadingScreen = document.getElementById('loading-screen'); 
const mainTerminalContainer = document.getElementById('main-terminal-container'); 
const initialLoadingBar = document.getElementById('initial-loading-bar'); 

let soundEnabled = true; 
let uptimeSeconds = 0;

const socket = io();

// --- Звуковые эффекты (для нажатий клавиш и команд) ---
const keyPressSounds = [
    new Audio('/static/audio/key_press_1.mp3'),
    new Audio('/static/audio/key_press_2.mp3'),
    new Audio('/static/audio/key_press_3.mp3')
];
const enterSounds = [
    new Audio('/static/audio/enter_1.mp3'),
    new Audio('/static/audio/enter_2.mp3'),
    new Audio('/static/audio/enter_3.mp3'),
];
const commandDoneSound = new Audio('/static/audio/command_done.mp3');

function playRandomSound(audioArray) {
    if (!soundEnabled || audioArray.length === 0) return;
    const sound = audioArray[Math.floor(Math.random() * audioArray.length)];
    sound.currentTime = 0;
    sound.volume = 0.6;
    sound.play().catch(e => console.log("Sound play error:", e));
}

function playSingleSound(audioElement) {
    if (!soundEnabled || !audioElement) return;
    audioElement.currentTime = 0;
    audioElement.volume = 0.7;
    audioElement.play().catch(e => console.log("Sound play error:", e));
}

// --- Объект плагинов команд ---
const commandPlugins = {};

// Функция регистрации команды
function registerCommand(name, handler) {
    commandPlugins[name.toLowerCase()] = handler;
}

// Пример плагина: команда 'echo'
registerCommand('echo', function(args) {
    const response = args.join(' ');
    displayOutput(response + '\n', false, true);
});


function initializeTerminalDisplay() {
    console.log("initializeTerminalDisplay: Запуск вывода начального текста.");
    displayOutput("Инициализация Терминала...", true, true);
    displayOutput("Связь установлена.", true, true);
    displayOutput("Доступ ограничен. Для получения доступа введите 'login <ключ>'", true, true);
    displayOutput("Для списка доступных команд введите \"help\"", true, true);
    displayOutput(prompt, false, true); // Отображаем prompt
    terminalInput.focus(); 
    console.log("initializeTerminalDisplay: Начальный текст выведен. Фокус на поле ввода.");
}


document.addEventListener('DOMContentLoaded', (event) => {
    console.log("DOMContentLoaded: DOM полностью загружен.");
    
    if (!loadingScreen || !mainTerminalContainer || !initialLoadingBar || !uiBottomPanel) {
        console.error("DOMContentLoaded: Один или несколько критических элементов UI отсутствуют!");
        return; 
    }

    // Восстановление данных из localStorage
    loadDataFromLocalStorage();

    mainTerminalContainer.classList.add('hidden');
    uiBottomPanel.classList.add('hidden'); 
    loadingScreen.classList.remove('hidden');
    initialLoadingBar.style.width = '0%'; 
    console.log("DOMContentLoaded: Скрыт mainTerminalContainer и uiBottomPanel, показан loadingScreen, полоса сброшена.");

    let progress = 0;
    const loadingInterval = setInterval(() => {
        progress += 10;
        if (progress > 100) progress = 100;
        initialLoadingBar.style.width = `${progress}%`;
        
        if (progress >= 100) {
            clearInterval(loadingInterval);
            console.log("Loading complete (100%). Clearing interval.");
            setTimeout(() => { 
                loadingScreen.classList.add('hidden'); 
                mainTerminalContainer.classList.remove('hidden'); 
                console.log("Loading screen hidden, Main terminal container shown.");
                initializeTerminalDisplay(); 
            }, 300); 
        }
    }, 80); 

    updateSystemTimeAndUptime();
    setInterval(updateSystemTimeAndUptime, 1000);

    if (toggleSoundButton) {
        toggleSoundButton.addEventListener('click', () => {
            soundEnabled = !soundEnabled;
            toggleSoundButton.textContent = `ЗВУК: ${soundEnabled ? 'ВКЛ' : 'ВЫКЛ'}`;
            saveDataToLocalStorage();
            console.log("Sound toggled:", soundEnabled ? 'ON' : 'OFF');
        });
    }

    if (rebootSystemButton) {
        rebootSystemButton.addEventListener('click', () => {
            console.log("Reboot system button clicked.");
            terminalOutput.value = ''; 
            terminalInput.value = '';
            terminalInput.disabled = true; 

            connectionStatusIndicator.textContent = "СОЕДИНЕНИЕ: ПЕРЕЗАГРУЗКА";
            connectionStatusIndicator.classList.remove('online', 'offline', 'warning');
            connectionStatusIndicator.classList.add('warning'); 
            
            systemTimeElement.textContent = "--:--:--";
            uptimeElement.textContent = "00:00:00";
            if (channelFrequencyElement) channelFrequencyElement.textContent = "--:--"; 
            uptimeSeconds = 0;

            if (uiBottomPanel) {
                uiBottomPanel.classList.add('hidden');
            }

            mainTerminalContainer.classList.add('hidden');
            loadingScreen.classList.remove('hidden');
            initialLoadingBar.style.width = '0%'; 
            console.log("Reboot: Hidden mainTerminalContainer, shown loadingScreen for reboot.");

            let rebootProgress = 0;
            const rebootInterval = setInterval(() => {
                rebootProgress += 10;
                if (rebootProgress > 100) rebootProgress = 100;
                initialLoadingBar.style.width = `${rebootProgress}%`;
                if (rebootProgress >= 100) {
                    clearInterval(rebootInterval);
                    console.log("Reboot loading complete (100%). Clearing interval.");
                    setTimeout(() => { 
                        loadingScreen.classList.add('hidden');
                        mainTerminalContainer.classList.remove('hidden');
                        terminalInput.disabled = false; 
                        terminalInput.focus();
                        console.log("Reboot: Loading screen hidden, Main terminal container shown after reboot.");
                        
                        connectionStatusIndicator.textContent = "СОЕДИНЕНИЕ: СТАБИЛЬНО";
                        connectionStatusIndicator.classList.remove('warning'); 
                        connectionStatusIndicator.classList.add('online');
                        
                        initializeTerminalDisplay(); 
                    }, 300); 
                }
            }, 80);
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
        } else {
            console.log("Enter pressed but still typing, ignoring command.");
        }
    } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (commandHistory.length > 0) { 
            if (historyIndex === -1) { 
                historyIndex = 0;
            } else if (historyIndex < commandHistory.length - 1) {
                historyIndex++;
            }
            terminalInput.value = commandHistory[historyIndex];
            setTimeout(() => { 
                terminalInput.selectionStart = terminalInput.selectionEnd = terminalInput.value.length;
            }, 0);
            console.log("History UP, current index:", historyIndex, "command:", terminalInput.value);
        }
    } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (historyIndex > 0) {
            historyIndex--;
            terminalInput.value = commandHistory[historyIndex];
            setTimeout(() => { 
                terminalInput.selectionStart = terminalInput.selectionEnd = terminalInput.value.length;
            }, 0);
            console.log("History DOWN, current index:", historyIndex, "command:", terminalInput.value);
        } else if (historyIndex === 0) {
            historyIndex = -1; 
            terminalInput.value = '';
            console.log("History DOWN, cleared input.");
        }
    }
});


socket.on('terminal_output', function(data) {
    console.log("Socket: Received terminal_output:", data.output);
    if (data.output === "<CLEAR_TERMINAL>\n") {
        terminalOutput.value = ''; 
        displayOutput(prompt, false, true); 
        playSingleSound(commandDoneSound);
        console.log("Terminal cleared.");
        return;
    }

    displayOutput(data.output, true);
    playSingleSound(commandDoneSound);
});

socket.on('update_ui_state', function(data) {
    console.log("Socket: Received update_ui_state:", data);
    const role = data.role;
    const channelFrequency = data.channel_frequency;

    if (uiBottomPanel) {
        if (['operative', 'commander', 'syndicate'].includes(role)) {
            uiBottomPanel.classList.remove('hidden');
            console.log("UI Bottom Panel shown for role:", role);
        } else {
            uiBottomPanel.classList.add('hidden');
            console.log("UI Bottom Panel hidden for role:", role);
        }
    }

    if (channelFrequencyElement && channelFrequency) {
        channelFrequencyElement.textContent = channelFrequency;
        console.log("Channel Frequency updated:", channelFrequency);
    }
});


function processCommand() {
    let fullCommand = terminalInput.value.trim();
    console.log("Processing command:", fullCommand);
    
    if (fullCommand === '') {
        displayOutput(prompt, false, true); 
        terminalInput.value = ''; 
        console.log("Empty command, showing prompt.");
        return;
    }

    if (commandHistory.length === 0 || commandHistory[0] !== fullCommand) {
        commandHistory.unshift(fullCommand);
        saveDataToLocalStorage();
        console.log("Command added to history.");
    }
    historyIndex = -1; 

    displayOutput(prompt + fullCommand, true, true); 
    console.log("Echoing command instantly:", prompt + fullCommand);

    const parts = fullCommand.split(' ');
    const cmdName = parts[0].toLowerCase();
    const args = parts.slice(1);

    if (commandPlugins[cmdName]) {
        commandPlugins[cmdName](args);
        terminalInput.value = ''; 
    } else {
        setTimeout(() => {
            socket.emit('terminal_input', { command: fullCommand });
            terminalInput.value = ''; 
            console.log("Command emitted to server, input cleared.");
        }, 50); 
    }
}

function displayOutput(text, addNewLine, isInstant = false) {
    console.log(`displayOutput called: text="${text.substring(0, 30)}...", addNewLine=${addNewLine}, isInstant=${isInstant}, isTyping=${isTyping}`);
    
    if (isTyping && !isInstant) { 
        console.log("Skipping displayOutput: Still typing and not instant.");
        return; 
    }

    if (isInstant) {
        terminalOutput.value += text;
        if (addNewLine) {
            terminalOutput.value += '\n'; 
        }
        terminalOutput.scrollTop = terminalOutput.scrollHeight; 
        terminalInput.focus();
        console.log("Instant output completed. Output value length:", terminalOutput.value.length);
        return;
    }

    isTyping = true;
    let i = 0;
    
    function typeChar() {
        if (i < text.length) {
            terminalOutput.value += text.charAt(i);
            i++;
            terminalOutput.scrollTop = terminalOutput.scrollHeight; 
            setTimeout(typeChar, TYPING_SPEED);
        } else {
            if (addNewLine) {
                terminalOutput.value += '\n'; 
            }
            isTyping = false;
            console.log("Typing animation finished. Final output value length:", terminalOutput.value.length);
            
            if (!text.endsWith(prompt + '\n') && !text.includes("Сеанс завершен") && !text.includes("Для повторного доступа")) {
                displayOutput(prompt, false, true); 
            }
            
            if (terminalInput.disabled && !text.includes("Сеанс завершен")) {
                terminalInput.disabled = false;
                terminalInput.focus();
                console.log("Input enabled and focused after typing.");
            } else if (!terminalInput.disabled) {
                terminalInput.focus();
                console.log("Input focused after typing.");
            }
            terminalOutput.scrollTop = terminalOutput.scrollHeight; 
        }
    }
    typeChar();
}


function updateSystemTimeAndUptime() {
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    if (systemTimeElement) {
        systemTimeElement.textContent = `${hours}:${minutes}:${seconds}`;
    }

    uptimeSeconds++;
    const uptHours = String(Math.floor(uptimeSeconds / 3600)).padStart(2, '0');
    const uptMinutes = String(Math.floor((uptimeSeconds % 3600) / 60)).padStart(2, '0');
    const uptSeconds = String(uptimeSeconds % 60).padStart(2, '0');
    if (uptimeElement) {
        uptimeElement.textContent = `${uptHours}:${uptMinutes}:${uptSeconds}`;
    }
}

// --- Работа с localStorage для автосохранения ---
function saveDataToLocalStorage() {
    try {
        localStorage.setItem('stalker_terminal_commandHistory', JSON.stringify(commandHistory));
        localStorage.setItem('stalker_terminal_terminalOutput', terminalOutput.value);
        localStorage.setItem('stalker_terminal_soundEnabled', JSON.stringify(soundEnabled));
        console.log("Data saved to localStorage.");
    } catch (e) {
        console.warn("Failed to save data to localStorage:", e);
    }
}

function loadDataFromLocalStorage() {
    try {
        const savedHistory = JSON.parse(localStorage.getItem('stalker_terminal_commandHistory'));
        const savedOutput = localStorage.getItem('stalker_terminal_terminalOutput');
        const savedSound = JSON.parse(localStorage.getItem('stalker_terminal_soundEnabled'));

        if (Array.isArray(savedHistory)) {
            commandHistory = savedHistory;
            console.log("Loaded command history from localStorage.");
        }
        if (typeof savedOutput === 'string') {
            terminalOutput.value = savedOutput;
            terminalOutput.scrollTop = terminalOutput.scrollHeight;
            console.log("Loaded terminal output from localStorage.");
        }
        if (typeof savedSound === 'boolean') {
            soundEnabled = savedSound;
            if(toggleSoundButton) {
                toggleSoundButton.textContent = `ЗВУК: ${soundEnabled ? 'ВКЛ' : 'ВЫКЛ'}`;
            }
            console.log("Loaded sound setting from localStorage:", soundEnabled);
        }
    } catch (e) {
        console.warn("Failed to load data from localStorage:", e);
    }
}
