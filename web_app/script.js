let tg = window.Telegram.WebApp;
let user = tg.initDataUnsafe?.user || { id: 0, username: "странник" };
tg.expand();

let modal = document.getElementById("gameModal");
let modalTitle = document.getElementById("modalTitle");
let modalBody = document.getElementById("modalBody");
let resultDiv = document.getElementById("gameResult");

async function apiCall(action, data = {}) {
    data.user_id = user.id;
    data.action = action;
    try {
        let res = await fetch("/api", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });
        return await res.json();
    } catch(e) {
        console.error(e);
        return { error: "тишина в эфире" };
    }
}

function showToast(msg, isWin = null) {
    let toast = document.createElement("div");
    toast.className = "toast-mystic";
    if (isWin === true) toast.style.borderColor = "#b8aee0";
    if (isWin === false) toast.style.borderColor = "#6a5a8a";
    toast.innerHTML = `<i class="fas ${isWin === true ? 'fa-crown' : 'fa-skull'}"></i> ${msg}`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2600);
}

function setOracle(text, isWin = null) {
    if (resultDiv) {
        resultDiv.innerHTML = `<i class="fas ${isWin === true ? 'fa-star' : 'fa-moon'}"></i> ${text}`;
        if (isWin === true) resultDiv.style.borderLeftColor = "#b8aee0";
        if (isWin === false) resultDiv.style.borderLeftColor = "#6a5a8a";
        setTimeout(() => {
            if (resultDiv.innerHTML === `<i class="fas ${isWin === true ? 'fa-star' : 'fa-moon'}"></i> ${text}`)
                resultDiv.innerHTML = "";
        }, 2800);
    }
}

async function refreshProfile() {
    let data = await apiCall("profile");
    if (data.coins !== undefined) {
        document.getElementById("balance").innerText = data.coins;
        document.getElementById("gamesCount").innerText = data.games;
        document.getElementById("winsCount").innerText = data.wins;
        document.getElementById("username").innerText = user.username;
    }
}

document.getElementById("bonusBtn")?.addEventListener("click", async () => {
    let data = await apiCall("bonus");
    if (data.success) {
        await refreshProfile();
        setOracle(`дар получен +${data.message}`, true);
        showToast(`+${data.message} эфира`, true);
    } else {
        showToast(data.message || "дар уже был сегодня", false);
    }
});

function openModal(title, html) {
    modalTitle.innerHTML = `<i class="fas fa-dice"></i> ${title}`;
    modalBody.innerHTML = html;
    modal.style.display = "flex";
}

function closeModal() {
    modal.style.display = "none";
}
document.querySelectorAll(".modal-closer").forEach(btn => btn.addEventListener("click", closeModal));
window.onclick = e => { if (e.target === modal) closeModal(); };

function gameDice1() {
    let btns = "";
    for (let i = 1; i <= 6; i++) btns += `<button class="dice-btn" data-dice="${i}">${i}</button>`;
    openModal("грань судьбы", `<div class="dice-group">${btns}</div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let val = parseInt(btn.dataset.dice);
            let res = await apiCall("dice1", { guess: val });
            await refreshProfile();
            if (res.error) showToast(res.error, false);
            else if (res.win) setOracle(`выпало ${res.roll} ✦ победа +${res.message}`, true);
            else setOracle(`выпало ${res.roll} ✦ бездна ${res.message}`, false);
            closeModal();
        });
    });
}

function gameDice2() {
    let btns = "";
    for (let i = 2; i <= 12; i++) btns += `<button class="dice-btn" data-dice="${i}">${i}</button>`;
    openModal("двойной рок", `<div class="dice-group">${btns}</div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let guess = parseInt(btn.dataset.dice);
            let res = await apiCall("dice2", { guess });
            await refreshProfile();
            if (res.error) showToast(res.error, false);
            else if (res.win) setOracle(`${res.dice[0]}+${res.dice[1]}=${res.total} ✦ победа +${res.message}`, true);
            else setOracle(`${res.dice[0]}+${res.dice[1]}=${res.total} ✦ бездна ${res.message}`, false);
            closeModal();
        });
    });
}

function gameRPS() {
    openModal("дуэль", `<div style="display:flex; gap:12px; justify-content:center;">
        <button class="dice-btn" data-choice="камень"><i class="fas fa-hand-rock"></i> камень</button>
        <button class="dice-btn" data-choice="ножницы"><i class="fas fa-hand-peace"></i> ножницы</button>
        <button class="dice-btn" data-choice="бумага"><i class="fas fa-hand-paper"></i> бумага</button>
    </div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let choice = btn.dataset.choice;
            let res = await apiCall("rps", { choice });
            await refreshProfile();
            if (res.error) showToast(res.error, false);
            else if (res.win) setOracle(`бот: ${res.bot} ✦ победа +${res.message}`, true);
            else if (res.message === "0") setOracle(`ничья (${res.bot})`, false);
            else setOracle(`бот: ${res.bot} ✦ бездна ${res.message}`, false);
            closeModal();
        });
    });
}

function gameSlots() {
    openModal("зов волн", `<button id="slotBtn" class="dice-btn" style="width:100%"><i class="fas fa-gamepad"></i> крутить (1 эфир)</button>`);
    document.getElementById("slotBtn")?.addEventListener("click", async () => {
        let res = await apiCall("slots");
        await refreshProfile();
        if (res.error) showToast(res.error, false);
        else if (res.win) setOracle(`${res.reel.join(" ")} ✦ джекпот +${res.message}`, true);
        else setOracle(`${res.reel.join(" ")} ✦ тишина ${res.message}`, false);
        closeModal();
    });
}

function gameGuess() {
    let btns = "";
    for (let i = 1; i <= 10; i++) btns += `<button class="dice-btn" data-guess="${i}">${i}</button>`;
    openModal("оракул", `<div class="dice-group">${btns}</div>`);
    document.querySelectorAll("#modalBody .dice-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            let guess = parseInt(btn.dataset.guess);
            let res = await apiCall("guess", { guess });
            await refreshProfile();
            if (res.error) showToast(res.error, false);
            else if (res.win) setOracle(`знак ${res.secret} ✦ победа +${res.message}`, true);
            else setOracle(`знак ${res.secret} ✦ пустота ${res.message}`, false);
            closeModal();
        });
    });
}

document.querySelectorAll(".game-card").forEach(card => {
    card.addEventListener("click", () => {
        let game = card.dataset.game;
        if (game === "dice1") gameDice1();
        if (game === "dice2") gameDice2();
        if (game === "rps") gameRPS();
        if (game === "slots") gameSlots();
        if (game === "guess") gameGuess();
    });
});

// Возврат на главную по клику на логотип
document.getElementById("logoHome")?.addEventListener("click", () => {
    document.querySelectorAll(".menu-btn").forEach(btn => btn.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach(pane => pane.classList.remove("active"));
    document.querySelector(".menu-btn[data-tab='games']").classList.add("active");
    document.getElementById("games").classList.add("active");
});

// Питомцы
async function loadPets() {
    let data = await apiCall("get_pets");
    let myDiv = document.getElementById("myPets");
    let shopDiv = document.getElementById("shopPets");
    if (!myDiv || !shopDiv) return;
    myDiv.innerHTML = "";
    shopDiv.innerHTML = "";
    for (let p of data.pets) {
        if (p.owned) {
            myDiv.innerHTML += `<div class="pet-card">
                <div class="pet-info"><i class="fas fa-dragon"></i><div><div class="pet-name">${p.emoji} ${p.name}</div><div class="pet-level">ур. ${p.level}</div></div></div>
                <div class="pet-actions"><button class="pet-btn" data-feed="${p.id}"><i class="fas fa-apple-alt"></i> кормить</button>
                <button class="pet-btn" data-collect="${p.id}"><i class="fas fa-coins"></i> собрать</button></div>
            </div>`;
        } else {
            shopDiv.innerHTML += `<div class="pet-card">
                <div class="pet-info"><i class="fas fa-egg"></i><div><div class="pet-name">${p.emoji} ${p.name}</div></div></div>
                <div class="pet-actions"><span class="pet-level">💰 ${p.price}</span><button class="pet-btn" data-buy="${p.id}">призвать</button></div>
            </div>`;
        }
    }
    document.querySelectorAll("[data-buy]").forEach(btn => {
        btn.addEventListener("click", async () => {
            let petId = parseInt(btn.dataset.buy);
            let res = await apiCall("buy_pet", { pet_id: petId });
            if (res.success) {
                await refreshProfile();
                await loadPets();
                showToast(res.message, true);
            } else showToast(res.message, false);
        });
    });
    document.querySelectorAll("[data-feed]").forEach(btn => {
        btn.addEventListener("click", async () => {
            let petId = parseInt(btn.dataset.feed);
            let res = await apiCall("feed_pet", { pet_id: petId });
            if (res.success) {
                await refreshProfile();
                await loadPets();
                showToast(res.message, true);
            } else showToast(res.message, false);
        });
    });
    document.querySelectorAll("[data-collect]").forEach(btn => {
        btn.addEventListener("click", async () => {
            let petId = parseInt(btn.dataset.collect);
            let res = await apiCall("collect_pet", { pet_id: petId });
            if (res.success) {
                await refreshProfile();
                showToast(`собрано +${res.earned} эфира`, true);
                if (res.earned > 0) setOracle(`+${res.earned} эфира от питомца`, true);
            }
        });
    });
}

async function loadAlliances() {
    let data = await apiCall("alliance_info");
    let panel = document.getElementById("alliancePanel");
    let topDiv = document.getElementById("topAlliances");
    if (!panel) return;
    panel.innerHTML = `<div class="alliance-card">
        <div><i class="fas fa-shield-alt"></i> твой альянс: ${data.alliance_id || "нет"}</div>
        <button id="createAllianceBtn" class="pet-btn"><i class="fas fa-plus"></i> создать</button>
        <button id="joinAllianceBtn" class="pet-btn"><i class="fas fa-sign-in-alt"></i> вступить</button>
    </div>`;
    if (topDiv && data.top) {
        topDiv.innerHTML = data.top.map(t => `<div><i class="fas fa-trophy"></i> ${t[0]} — ${t[1]} эфира</div>`).join("");
    }
    document.getElementById("createAllianceBtn")?.addEventListener("click", () => {
        let name = prompt("название альянса");
        let min = parseInt(prompt("мин. эфира для входа (0-100000)") || "0");
        apiCall("create_alliance", { name, min_coins: min }).then(res => {
            if (res.success) loadAlliances();
            else showToast("ошибка", false);
        });
    });
    document.getElementById("joinAllianceBtn")?.addEventListener("click", () => {
        let id = parseInt(prompt("id альянса"));
        apiCall("join_alliance", { alliance_id: id }).then(res => {
            if (res.success) loadAlliances();
            else showToast("не удалось", false);
        });
    });
}

document.querySelectorAll(".menu-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".menu-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");
        let tab = btn.dataset.tab;
        document.getElementById(tab).classList.add("active");
        if (tab === "pets") loadPets();
        if (tab === "alliances") loadAlliances();
    });
});

refreshProfile();
loadPets();
loadAlliances();
