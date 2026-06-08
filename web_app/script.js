let tg = window.Telegram.WebApp;
let user = tg.initDataUnsafe?.user || { id: 0, username: "Игрок" };
tg.expand();

let currentGame = null;

async function api(action, data = {}) {
    data.user_id = user.id;
    data.action = action;
    let res = await fetch('/api', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    return await res.json();
}

async function loadProfile() {
    let data = await api('profile');
    document.getElementById('balance').innerText = data.coins;
    document.getElementById('gamesCount').innerText = data.games;
    document.getElementById('winsCount').innerText = data.wins;
    document.getElementById('username').innerText = user.username;
}

async function getBonus() {
    let data = await api('bonus');
    if (data.success) {
        await loadProfile();
        showResult(data.message);
    }
}

function showResult(msg) {
    let div = document.getElementById('result');
    div.innerHTML = msg;
    setTimeout(() => { if (div.innerHTML === msg) div.innerHTML = ""; }, 2000);
}

// Игры
function gameDice1() {
    let html = `<div class="dice-grid">`;
    for (let i = 1; i <= 6; i++) {
        html += `<button class="dice-btn" onclick="playDice1(${i})">${i}</button>`;
    }
    html += `</div>`;
    showModal("1 КУБИК", html);
    currentGame = "dice1";
}

async function playDice1(guess) {
    let data = await api('dice1', { guess: guess });
    if (data.success) {
        await loadProfile();
        let msg = data.win ? `🎲 ${data.roll} Победа! ${data.message}` : `🎲 ${data.roll} Проигрыш ${data.message}`;
        showResult(msg);
        closeModal();
    } else {
        showResult(data.message);
    }
}

function gameDice2() {
    let html = `<div class="dice-grid">`;
    for (let i = 2; i <= 12; i++) {
        html += `<button class="dice-btn" onclick="playDice2(${i})">${i}</button>`;
    }
    html += `</div>`;
    showModal("2 КУБИКА", html);
}

async function playDice2(guess) {
    let data = await api('dice2', { guess: guess });
    if (data.success) {
        await loadProfile();
        let msg = data.win ? `🎲 ${data.dice[0]}+${data.dice[1]}=${data.roll} Победа! ${data.message}` : `🎲 ${data.dice[0]}+${data.dice[1]}=${data.roll} Проигрыш ${data.message}`;
        showResult(msg);
        closeModal();
    }
}

function gameRPS() {
    let html = `<div class="rps-group">
        <button class="rps-btn" onclick="playRPS('камень')">🪨</button>
        <button class="rps-btn" onclick="playRPS('ножницы')">✂️</button>
        <button class="rps-btn" onclick="playRPS('бумага')">📄</button>
    </div>`;
    showModal("КНБ", html);
}

async function playRPS(choice) {
    let data = await api('rps', { choice: choice });
    if (data.success) {
        await loadProfile();
        let msg = data.win ? `🤖 ${data.bot} Победа! ${data.message}` : `🤖 ${data.bot} ${data.message === "0" ? "Ничья" : "Проигрыш"}`;
        showResult(msg);
        closeModal();
    }
}

function gameSlots() {
    let html = `<button class="slot-btn" onclick="playSlots()">🎰 КРУТИТЬ (1💰)</button>`;
    showModal("СЛОТЫ", html);
}

async function playSlots() {
    let data = await api('slots');
    if (data.success) {
        await loadProfile();
        let msg = data.win ? `🎰 ${data.reel.join(" ")} Победа! ${data.message}` : `🎰 ${data.reel.join(" ")} Проигрыш ${data.message}`;
        showResult(msg);
        closeModal();
    }
}

function gameGuess() {
    let html = `<div class="dice-grid">`;
    for (let i = 1; i <= 10; i++) {
        html += `<button class="dice-btn" onclick="playGuess(${i})">${i}</button>`;
    }
    html += `</div>`;
    showModal("УГАДАЙ ЧИСЛО", html);
}

async function playGuess(guess) {
    let data = await api('guess', { guess: guess });
    if (data.success) {
        await loadProfile();
        let msg = data.win ? `🔢 ${data.secret} Победа! ${data.message}` : `🔢 ${data.secret} Проигрыш ${data.message}`;
        showResult(msg);
        closeModal();
    }
}

// Модалка
function showModal(title, body) {
    document.getElementById('modalTitle').innerText = title;
    document.getElementById('modalBody').innerHTML = body;
    document.getElementById('modal').style.display = 'flex';
}

function closeModal() {
    document.getElementById('modal').style.display = 'none';
}

// Вкладки
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).classList.add('active');
    });
});

loadProfile();
