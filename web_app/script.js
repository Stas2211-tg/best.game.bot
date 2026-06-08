let tg = window.Telegram.WebApp;
let user = tg.initDataUnsafe?.user || { id: 0, username: "NYXARA" };

tg.expand();
tg.MainButton.hide();

// Глобальные переменные
let currentGame = null;
let currentGameData = null;

// ========== API ВЫЗОВЫ ==========
async function apiCall(action, data = {}) {
    data.user_id = user.id;
    data.action = action;
    
    try {
        let response = await fetch('/api', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await response.json();
    } catch(e) {
        console.error(e);
        showToast("❌ Ошибка сети");
        return { success: false };
    }
}

// ========== УВЕДОМЛЕНИЯ ==========
function showToast(message, isError = false) {
    let toast = document.getElementById('toast');
    toast.textContent = message;
    toast.style.borderColor = isError ? '#ff4444' : '#ff00ff';
    toast.classList.add('show');
    setTimeout(() => {
        toast.classList.remove('show');
    }, 2500);
}

// ========== ЗАГРУЗКА ПРОФИЛЯ ==========
async function loadProfile() {
    let data = await apiCall('profile');
    if (data.coins !== undefined) {
        document.getElementById('balance').innerText = data.coins;
        document.getElementById('games').innerText = data.total_games || 0;
        document.getElementById('wins').innerText = data.total_wins || 0;
        document.getElementById('username').innerText = data.username || "NYXARA";
    }
}

// ========== БОНУС ==========
async function getBonus() {
    let data = await apiCall('bonus');
    if (data.success) {
        showToast(data.message);
        await loadProfile();
    } else {
        showToast(data.message, true);
    }
}

// ========== РЕФЕРАЛЫ ==========
async function getReferral() {
    let data = await apiCall('referrals');
    if (data.success) {
        document.getElementById('referral-body').innerHTML = `
            <div style="text-align: center">
                <div style="font-size: 48px; margin-bottom: 16px">👥</div>
                <div style="margin-bottom: 16px">Приглашено друзей: <strong style="color:#ff00ff">${data.count}</strong></div>
                <div style="background:rgba(0,255,255,0.1); border-radius:12px; padding:12px; margin-bottom:16px; word-break:break-all">
                    <code style="font-size:11px">${data.link}</code>
                </div>
                <button class="btn btn-neon" onclick="copyToClipboard('${data.link}')">📋 КОПИРОВАТЬ ССЫЛКУ</button>
                <div style="margin-top: 16px; font-size: 12px; color:#888">За каждого друга +10💰 тебе и +5💰 другу!</div>
            </div>
        `;
        document.getElementById('referral-modal').style.display = 'flex';
    }
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text);
    showToast("✅ Ссылка скопирована!");
    closeReferralModal();
}

function closeReferralModal() {
    document.getElementById('referral-modal').style.display = 'none';
}

// ========== ИГРЫ ==========
function showGameModal(game) {
    currentGame = game;
    let modalBody = document.getElementById('game-modal-body');
    let title = document.getElementById('modal-title');
    
    switch(game) {
        case 'dice1':
            title.innerText = '🎲 1 КУБИК';
            modalBody.innerHTML = `
                <div style="text-align:center">
                    <div style="font-size:48px; margin-bottom:16px">🎲</div>
                    <div>Угадай число от 1 до 6</div>
                    <div class="dice-buttons">
                        ${[1,2,3,4,5,6].map(n => `<button class="dice-btn" onclick="playDice1(${n})">${n}</button>`).join('')}
                    </div>
                </div>
            `;
            break;
        case 'dice2':
            title.innerText = '🎲 2 КУБИКА';
            modalBody.innerHTML = `
                <div style="text-align:center">
                    <div style="font-size:48px; margin-bottom:16px">🎲🎲</div>
                    <div>Угадай сумму от 2 до 12</div>
                    <div class="dice-buttons">
                        ${[2,3,4,5,6,7,8,9,10,11,12].map(n => `<button class="dice-btn" onclick="playDice2(${n})">${n}</button>`).join('')}
                    </div>
                </div>
            `;
            break;
        case 'rps':
            title.innerText = '✂️ КАМЕНЬ-НОЖНИЦЫ-БУМАГА';
            modalBody.innerHTML = `
                <div style="text-align:center">
                    <div style="font-size:48px; margin-bottom:16px">✂️ 📄 🪨</div>
                    <div>Выбери свой ход</div>
                    <div class="rps-buttons">
                        <button class="rps-btn" onclick="playRPS('камень')">🪨</button>
                        <button class="rps-btn" onclick="playRPS('ножницы')">✂️</button>
                        <button class="rps-btn" onclick="playRPS('бумага')">📄</button>
                    </div>
                </div>
            `;
            break;
        case 'slots':
            title.innerText = '🎰 СЛОТЫ';
            modalBody.innerHTML = `
                <div style="text-align:center">
                    <div style="font-size:48px; margin-bottom:16px">🎰</div>
                    <button class="btn btn-neon" onclick="playSlots()">КРУТИТЬ (1💰)</button>
                </div>
            `;
            break;
        case 'guess':
            title.innerText = '🔢 УГАДАЙ ЧИСЛО';
            modalBody.innerHTML = `
                <div style="text-align:center">
                    <div style="font-size:48px; margin-bottom:16px">🔢</div>
                    <div>Угадай число от 1 до 10</div>
                    <div class="dice-buttons">
                        ${[1,2,3,4,5,6,7,8,9,10].map(n => `<button class="dice-btn" onclick="playGuessNumber(${n})">${n}</button>`).join('')}
                    </div>
                </div>
            `;
            break;
        case 'evenodd':
            title.innerText = '🎲 ЧЁТ/НЕЧЁТ';
            modalBody.innerHTML = `
                <div style="text-align:center">
                    <div style="font-size:48px; margin-bottom:16px">🎲</div>
                    <div>Угадай, чётное или нечётное выпадет число (1-10)</div>
                    <div class="evenodd-buttons">
                        <button class="evenodd-btn" onclick="playEvenOdd('чётное')">ЧЁТНОЕ</button>
                        <button class="evenodd-btn" onclick="playEvenOdd('нечётное')">НЕЧЁТНОЕ</button>
                    </div>
                </div>
            `;
            break;
    }
    
    document.getElementById('game-modal').style.display = 'flex';
}

function closeGameModal() {
    document.getElementById('game-modal').style.display = 'none';
    currentGame = null;
}

async function playDice1(guess) {
    let data = await apiCall('dice1', { bet: 1, guess: guess });
    if (data.success) {
        await loadProfile();
        showToast(data.message);
        let resultDiv = document.getElementById('game-result');
        if (resultDiv) {
            resultDiv.innerHTML = `<div style="font-size:24px">🎲 ${data.roll}</div><div>${data.message}</div>`;
            setTimeout(() => resultDiv.innerHTML = '', 3000);
        }
        closeGameModal();
    } else {
        showToast(data.message, true);
    }
}

async function playDice2(guess) {
    let data = await apiCall('dice2', { bet: 1, guess: guess });
    if (data.success) {
        await loadProfile();
        showToast(data.message);
        let resultDiv = document.getElementById('game-result');
        if (resultDiv) {
            resultDiv.innerHTML = `<div style="font-size:24px">🎲 ${data.dice[0]}+${data.dice[1]}=${data.roll}</div><div>${data.message}</div>`;
            setTimeout(() => resultDiv.innerHTML = '', 3000);
        }
        closeGameModal();
    } else {
        showToast(data.message, true);
    }
}

async function playRPS(choice) {
    let data = await apiCall('rps', { choice: choice });
    if (data.success) {
        await loadProfile();
        showToast(data.message);
        let resultDiv = document.getElementById('game-result');
        if (resultDiv) {
            resultDiv.innerHTML = `<div>🤖 Бот выбрал: ${data.bot}</div><div>${data.message}</div>`;
            setTimeout(() => resultDiv.innerHTML = '', 3000);
        }
        closeGameModal();
    } else {
        showToast(data.message, true);
    }
}

async function playSlots() {
    let data = await apiCall('slots');
    if (data.success) {
        await loadProfile();
        showToast(data.message);
        let resultDiv = document.getElementById('game-result');
        if (resultDiv) {
            resultDiv.innerHTML = `<div style="font-size:28px">${data.reel[0]} ${data.reel[1]} ${data.reel[2]}</div><div>${data.message}</div>`;
            setTimeout(() => resultDiv.innerHTML = '', 3000);
        }
        closeGameModal();
    } else {
        showToast(data.message, true);
    }
}

async function playGuessNumber(guess) {
    let data = await apiCall('guess_number', { bet: 1, guess: guess });
    if (data.success) {
        await loadProfile();
        showToast(data.message);
        let resultDiv = document.getElementById('game-result');
        if (resultDiv) {
            resultDiv.innerHTML = `<div style="font-size:24px">🔢 Загадано: ${data.secret}</div><div>${data.message}</div>`;
            setTimeout(() => resultDiv.innerHTML = '', 3000);
        }
        closeGameModal();
    } else {
        showToast(data.message, true);
    }
}

async function playEvenOdd(choice) {
    let num = Math.floor(Math.random() * 10) + 1;
    let isEven = num % 2 === 0;
    let correct = isEven ? 'чётное' : 'нечётное';
    let win = choice === correct;
    
    if (!win) {
        let data = await apiCall('profile');
        if (data.coins < 1) {
            showToast("❌ Нет монет", true);
            return;
        }
    }
    
    let data = await apiCall('guess_number', { bet: 1, guess: num });
    if (data.success) {
        await loadProfile();
        if (win) {
            showToast(`🎲 ${num} (${correct}) Победа! +2💰`);
        } else {
            showToast(`🎲 ${num} (${correct}) Проигрыш!`);
        }
        closeGameModal();
    }
}

// ========== КЛАНЫ ==========
async function loadClan() {
    let data = await apiCall('get_clan');
    let clanDiv = document.getElementById('clan-info');
    
    if (data.success && data.has_clan) {
        clanDiv.innerHTML = `
            <div class="clan-emoji">${data.clan.emoji}</div>
            <div class="clan-name">${data.clan.name}</div>
            <div class="clan-owner">👑 Владелец: ${data.clan.owner_id}</div>
        `;
    } else {
        clanDiv.innerHTML = `
            <div class="loading-spinner"></div>
            <div class="loading-text">ВЫ НЕ В КЛАНЕ</div>
        `;
    }
}

function showCreateClan() {
    let modalBody = document.getElementById('game-modal-body');
    document.getElementById('modal-title').innerText = '📋 СОЗДАТЬ КЛАН';
    modalBody.innerHTML = `
        <input type="text" id="clan-name" class="modal-input" placeholder="Название клана" maxlength="20">
        <input type="text" id="clan-emoji" class="modal-input" placeholder="Эмодзи (1 символ)" maxlength="2">
        <button class="btn btn-neon" onclick="createClan()">СОЗДАТЬ</button>
    `;
    currentGame = 'create_clan';
    document.getElementById('game-modal').style.display = 'flex';
}

async function createClan() {
    let name = document.getElementById('clan-name')?.value;
    let emoji = document.getElementById('clan-emoji')?.value;
    if (!name || !emoji) {
        showToast("❌ Заполните все поля", true);
        return;
    }
    let data = await apiCall('create_clan', { name: name, emoji: emoji });
    showToast(data.message);
    if (data.success) {
        closeGameModal();
        await loadClan();
    }
}

function showJoinClan() {
    let modalBody = document.getElementById('game-modal-body');
    document.getElementById('modal-title').innerText = '🔍 ВСТУПИТЬ В КЛАН';
    modalBody.innerHTML = `
        <input type="number" id="clan-id" class="modal-input" placeholder="ID клана">
        <button class="btn btn-neon" onclick="joinClan()">ВСТУПИТЬ</button>
    `;
    currentGame = 'join_clan';
    document.getElementById('game-modal').style.display = 'flex';
}

async function joinClan() {
    let clanId = document.getElementById('clan-id')?.value;
    if (!clanId) {
        showToast("❌ Введите ID клана", true);
        return;
    }
    let data = await apiCall('join_clan', { clan_id: parseInt(clanId) });
    showToast(data.message);
    if (data.success) {
        closeGameModal();
        await loadClan();
    }
}

async function leaveClan() {
    let data = await apiCall('leave_clan');
    showToast(data.message);
    if (data.success) {
        await loadClan();
    }
}

// ========== ВКЛАДКИ ==========
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        btn.classList.add('active');
        let tabId = btn.dataset.tab + '-tab';
        document.getElementById(tabId).classList.add('active');
        
        if (btn.dataset.tab === 'clans') loadClan();
        if (btn.dataset.tab === 'profile') loadProfile();
    });
});

// ========== ЗАКРЫТИЕ МОДАЛЬНЫХ ОКОН ==========
window.onclick = function(event) {
    let modal = document.getElementById('game-modal');
    let referralModal = document.getElementById('referral-modal');
    if (event.target === modal) closeGameModal();
    if (event.target === referralModal) closeReferralModal();
}

// ========== СТАРТ ==========
loadProfile();