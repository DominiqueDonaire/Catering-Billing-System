const API = 'http://127.0.0.1:5000';

async function login() {
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value.trim();

  hideMessages();

  if (!username || !password) {
    showError('Please enter your username and password');
    return;
  }

  const btn = document.querySelector('.btn-login');
  btn.textContent = 'Signing in...';
  btn.disabled = true;

  try {
    const res = await fetch(`${API}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        Username: username,
        Password: password
      })
    });

    const data = await res.json();
    btn.textContent = 'SIGN IN';
    btn.disabled = false;

    if (res.status === 401) {
      if (data.error === 'Username not found') {
        showError('Username does not exist. Please check and try again.');
      } else if (data.error === 'Incorrect password') {
        showError('Incorrect password. Please try again.');
        const pwdField = document.getElementById('password');
        pwdField.style.borderBottomColor = '#e53935';
        pwdField.value = '';
        pwdField.focus();
        setTimeout(() => { pwdField.style.borderBottomColor = ''; }, 2000);
      }
      return;
    }

    if (!res.ok) {
      showError('Something went wrong. Please try again.');
      return;
    }

    localStorage.setItem('role', data.role);
    localStorage.setItem('username', data.username);
    localStorage.setItem('customer_id', data.customer_id ?? '');

    showSuccess(`Welcome ${data.username}! Redirecting...`);
    setTimeout(() => {
      window.location.href = 'dashboard.html';
    }, 1200);

  } catch (err) {
    btn.textContent = 'SIGN IN';
    btn.disabled = false;
    showError('Cannot connect to server. Make sure Flask is running.');
  }
}

async function register() {
  const fname    = document.getElementById('fname').value.trim();
  const lname    = document.getElementById('lname').value.trim();
  const username = document.getElementById('username').value.trim();
  const email    = document.getElementById('email').value.trim();
  const phone    = document.getElementById('phone').value.trim();
  const password = document.getElementById('password').value;
  const confirm  = document.getElementById('confirm-password').value;
  const role     = document.getElementById('role').value;

  hideMessages();

  // validations
  if (!fname || !lname || !username || !email || !phone || !password || !confirm) {
    showError('Please fill in all fields');
    return;
  }
  if (!/^\S+@\S+\.\S+$/.test(email)) {
    showError('Please enter a valid email address');
    return;
  }
  if (!/^09\d{9}$/.test(phone)) {
    showError('Phone must be 11 digits starting with 09');
    return;
  }
  if (password.length < 6) {
    showError('Password must be at least 6 characters');
    return;
  }
  if (password !== confirm) {
    showError('Passwords do not match');
    return;
  }

  const btn = document.getElementById('reg-btn');
  btn.textContent = 'Creating account...';
  btn.disabled = true;

  try {
    const res = await fetch(`${API}/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        FirstName: fname,
        LastName:  lname,
        Username:  username,
        Email:     email,
        Phone:     phone,
        Password:  password,
        Role:      role
      })
    });

    const data = await res.json();
    btn.textContent = 'SIGN UP';
    btn.disabled = false;

    if (!res.ok) {
      showError(`${data.error}`);
      return;
    }

    // show success and countdown
    let countdown = 3;
    const suc = document.getElementById('success-msg');
    suc.style.display = 'block';
    suc.innerHTML = `Account created successfully! Redirecting to login in <strong>${countdown}</strong>s...`;

    const timer = setInterval(() => {
      countdown--;
      suc.innerHTML = `Account created successfully! Redirecting to login in <strong>${countdown}</strong>s...`;
      if (countdown <= 0) {
        clearInterval(timer);
        window.location.href = 'login.html';
      }
    }, 1000);

  } catch (err) {
    btn.textContent = 'SIGN UP';
    btn.disabled = false;
    showError('Cannot connect to server. Make sure Flask is running.');
  }
}

// ── HELPERS ──
function showError(msg) {
  const err = document.getElementById('error-msg');
  const suc = document.getElementById('success-msg');
  if (suc) suc.style.display = 'none';
  if (err) {
    err.style.display = 'block';
    err.innerHTML = msg;
  }
}

function showSuccess(msg) {
  const err = document.getElementById('error-msg');
  const suc = document.getElementById('success-msg');
  if (err) err.style.display = 'none';
  if (suc) {
    suc.style.display = 'block';
    suc.innerHTML = msg;
  }
}

function hideMessages() {
  const err = document.getElementById('error-msg');
  const suc = document.getElementById('success-msg');
  if (err) err.style.display = 'none';
  if (suc) suc.style.display = 'none';
}
