// Estúdio 3D voxel: monta a cena a partir de um storyboard e desenha qualquer instante t (segundos).
// Tudo é determinístico (sem relógio, sem aleatório solto): o mesmo t sempre gera o mesmo quadro,
// então o Python pode gravar quadro a quadro na velocidade que der.
//
//   window.preparar(storyboard)  → monta cenários, personagens e objetos (devolve a duração)
//   window.quadro(t)             → desenha o instante t
import * as THREE from "./vendor/three.module.min.js";

const W = 1080, H = 1920;
const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById("tela"), antialias: true,
                                           preserveDrawingBuffer: true });
renderer.setSize(W, H, false);
renderer.setPixelRatio(1);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.3;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(42, W / H, 0.1, 600);

// ---------- utilidades ----------

function semente(n) {  // aleatório reproduzível (mulberry32)
  let a = n >>> 0;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const lerp = (a, b, k) => a + (b - a) * k;
const clamp01 = (x) => Math.min(Math.max(x, 0), 1);
const suave = (x) => { x = clamp01(x); return x * x * (3 - 2 * x); };
const elastico = (x) => {  // "pop" com leve sobra
  x = clamp01(x);
  return x === 0 || x === 1 ? x : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * (2 * Math.PI) / 3) + 1;
};

const MATS = new Map();
function mat(cor, extra = {}) {
  const chave = cor + JSON.stringify(extra);
  if (!MATS.has(chave)) MATS.set(chave, new THREE.MeshStandardMaterial({ color: cor, roughness: 0.82, metalness: 0.02, ...extra }));
  return MATS.get(chave);
}
function luz(cor, forca = 2.2) { return mat(cor, { emissive: cor, emissiveIntensity: forca, roughness: 0.4 }); }

function caixa(w, h, d, material, x = 0, y = 0, z = 0, pai = null) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), typeof material === "string" ? mat(material) : material);
  m.position.set(x, y, z);
  m.castShadow = true;
  m.receiveShadow = true;
  if (pai) pai.add(m);
  return m;
}
function grupo(x = 0, y = 0, z = 0, pai = null) {
  const g = new THREE.Group();
  g.position.set(x, y, z);
  if (pai) pai.add(g);
  return g;
}

// ---------- personagens ----------

// Explorador: moletom verde-água, cabelo em blocos. Partes com pivô nas juntas pra animar.
function criarExplorador() {
  const p = {};
  const raiz = grupo();
  const corpo = grupo(0, 0, 0, raiz);
  p.raiz = raiz; p.corpo = corpo;

  const pele = "#c9875c", moletom = "#1fa39a", moletomEsc = "#178079", calca = "#252a4a", tenis = "#f1f1f1";
  const cabelo = "#2a1a12", olho = "#ffffff";

  for (const lado of [-1, 1]) {  // pernas (pivô no quadril)
    const perna = grupo(0.22 * lado, 1.0, 0, corpo);
    caixa(0.38, 0.86, 0.42, calca, 0, -0.43, 0, perna);
    caixa(0.42, 0.2, 0.58, tenis, 0, -0.92, 0.06, perna);
    p[lado < 0 ? "pernaE" : "pernaD"] = perna;
  }
  const tronco = grupo(0, 1.0, 0, corpo);
  p.tronco = tronco;
  caixa(1.04, 1.02, 0.62, moletom, 0, 0.5, 0, tronco);
  caixa(0.7, 0.3, 0.06, moletomEsc, 0, 0.22, 0.33, tronco);           // bolso
  caixa(0.06, 0.32, 0.05, "#f4f4f4", -0.13, 0.78, 0.33, tronco);      // cordões
  caixa(0.06, 0.32, 0.05, "#f4f4f4", 0.13, 0.78, 0.33, tronco);
  caixa(0.9, 0.34, 0.3, moletomEsc, 0, 0.96, -0.3, tronco);           // capuz

  for (const lado of [-1, 1]) {  // braços (pivô no ombro)
    const braco = grupo(0.66 * lado, 0.92, 0, tronco);
    caixa(0.3, 0.84, 0.36, moletom, 0, -0.38, 0, braco);
    const mao = caixa(0.28, 0.26, 0.32, pele, 0, -0.9, 0, braco);
    braco.userData.mao = mao;
    p[lado < 0 ? "bracoE" : "bracoD"] = braco;
  }

  const cabeca = grupo(0, 1.05, 0, tronco);
  p.cabeca = cabeca;
  caixa(1.12, 1.0, 0.96, pele, 0, 0.52, 0, cabeca);
  caixa(1.2, 0.3, 1.04, cabelo, 0, 1.1, -0.02, cabeca);               // topo do cabelo
  caixa(1.2, 0.62, 0.26, cabelo, 0, 0.78, -0.42, cabeca);             // nuca
  caixa(0.18, 0.5, 0.9, cabelo, -0.6, 0.78, -0.05, cabeca);           // laterais
  caixa(0.18, 0.5, 0.9, cabelo, 0.6, 0.78, -0.05, cabeca);
  const r = semente(7);
  for (let i = 0; i < 6; i++) {                                        // franja em blocos
    caixa(0.22, 0.18 + r() * 0.16, 0.22, cabelo, -0.5 + i * 0.2, 0.93 - r() * 0.05, 0.42, cabeca);
  }
  caixa(0.14, 0.14, 0.1, "#b87650", 0, 0.42, 0.52, cabeca);            // nariz
  p.olhos = [];
  for (const lado of [-1, 1]) {
    const branco = caixa(0.26, 0.32, 0.04, olho, 0.25 * lado, 0.6, 0.49, cabeca);
    const pupila = caixa(0.13, 0.19, 0.03, "#141422", 0.25 * lado, 0.58, 0.515, cabeca);
    const sobr = caixa(0.32, 0.09, 0.05, cabelo, 0.25 * lado, 0.86, 0.49, cabeca);
    p.olhos.push({ branco, pupila, sobr, lado, x0: 0.25 * lado });
  }
  p.boca = caixa(0.32, 0.06, 0.03, "#3b1a1a", 0, 0.24, 0.49, cabeca);
  return p;
}

// Bit: robozinho-cubo roxo com rosto de tela. Faz as reações ao lado do explorador.
function criarBit() {
  const p = {};
  const raiz = grupo();
  const corpo = grupo(0, 0, 0, raiz);
  p.raiz = raiz; p.corpo = corpo;
  caixa(1.3, 1.1, 1.1, "#6d4bff", 0, 0.95, 0, corpo);
  caixa(1.0, 0.66, 0.05, "#191338", 0, 1.0, 0.56, corpo);              // tela do rosto
  for (const lado of [-1, 1]) caixa(0.24, 0.42, 0.24, "#2c2457", 0.34 * lado, 0.2, 0, corpo);
  caixa(0.06, 0.38, 0.06, "#2c2457", 0, 1.68, 0, corpo);               // antena
  // material próprio (não vai pro cache): a cor e o brilho mudam a cada quadro
  p.lampada = caixa(0.18, 0.18, 0.18, new THREE.MeshStandardMaterial({ color: "#ffd23f", emissive: "#ffd23f" }), 0, 1.92, 0, corpo);
  p.olhos = [];
  for (const lado of [-1, 1]) p.olhos.push(caixa(0.16, 0.22, 0.03, luz("#5cf2e3", 2.2), 0.24 * lado, 1.04, 0.6, corpo));
  p.boca = caixa(0.26, 0.05, 0.03, luz("#5cf2e3", 2.2), 0, 0.82, 0.6, corpo);
  return p;
}

// ---------- poses ----------

const ACOES = ["parado", "fala", "surpreso", "aponta", "pensa", "comemora", "medo", "acena", "anda"];

function posarExplorador(p, acao, tl, t, falando, dur) {
  const ent = suave(tl / 0.35);        // entrada da pose
  // base: respiração e balanço
  p.corpo.position.set(0, Math.sin(t * 2.2) * 0.02, 0);
  p.tronco.rotation.set(0, 0, Math.sin(t * 1.1) * 0.015);
  p.cabeca.rotation.set(Math.sin(t * 1.7) * 0.03, Math.sin(t * 0.9) * 0.08, 0);
  for (const b of [p.bracoE, p.bracoD]) b.rotation.set(0, 0, 0);
  p.bracoE.rotation.z = -0.08; p.bracoD.rotation.z = 0.08;
  p.pernaE.rotation.x = 0; p.pernaD.rotation.x = 0;
  let olhoEsc = 1, sobrY = 0.86, sobrRot = 0, olharX = Math.sin(t * 0.6) * 0.02, olharY = 0;

  if (acao === "surpreso") {
    const pulo = Math.max(0, Math.sin(clamp01(tl / 0.45) * Math.PI)) * 0.35;
    p.corpo.position.y += pulo;
    p.corpo.position.z = -0.25 * ent;
    p.bracoE.rotation.z = lerp(-0.08, -2.3, ent); p.bracoD.rotation.z = lerp(0.08, 2.3, ent);
    p.bracoE.rotation.x = p.bracoD.rotation.x = -0.3 * ent;
    olhoEsc = 1 + 0.35 * ent; sobrY = 0.86 + 0.1 * ent;
  } else if (acao === "aponta") {
    p.bracoD.rotation.z = lerp(0.08, 1.45, ent);
    p.bracoD.rotation.y = -0.2 * ent;
    p.tronco.rotation.y = 0.18 * ent;
    p.cabeca.rotation.y += 0.25 * ent;
    olharX = 0.04 * ent;
  } else if (acao === "pensa") {
    p.bracoD.rotation.x = -2.05 * ent; p.bracoD.rotation.z = -0.55 * ent;
    p.cabeca.rotation.z = 0.12 * ent; p.cabeca.rotation.x = -0.1 * ent;
    olharY = 0.05 * ent; olharX = 0.04 * ent; sobrRot = 0.12 * ent;
  } else if (acao === "comemora") {
    const salto = Math.abs(Math.sin(tl * 6.5)) * 0.32 * ent;
    p.corpo.position.y += salto;
    p.bracoE.rotation.z = -2.6 * ent + Math.sin(tl * 13) * 0.15; p.bracoD.rotation.z = 2.6 * ent - Math.sin(tl * 13) * 0.15;
    sobrY = 0.9;
  } else if (acao === "medo") {
    p.corpo.position.x = Math.sin(t * 60) * 0.025 * ent;
    p.corpo.position.z = -0.2 * ent;
    p.bracoE.rotation.x = p.bracoD.rotation.x = -1.2 * ent;
    p.bracoE.rotation.z = -0.5 * ent; p.bracoD.rotation.z = 0.5 * ent;
    p.cabeca.rotation.x = 0.12 * ent;
    sobrRot = -0.3 * ent; olhoEsc = 1.2;
  } else if (acao === "acena") {
    p.bracoD.rotation.z = 2.5 * ent + Math.sin(tl * 9) * 0.35 * ent;
  } else if (acao === "anda") {
    const passo = Math.sin(tl * 7);
    p.pernaE.rotation.x = passo * 0.5; p.pernaD.rotation.x = -passo * 0.5;
    p.bracoE.rotation.x = -passo * 0.45; p.bracoD.rotation.x = passo * 0.45;
    p.corpo.position.y += Math.abs(Math.cos(tl * 7)) * 0.06;
  } else if (acao === "fala") {
    p.bracoD.rotation.x = -0.5 * ent + Math.sin(t * 3) * 0.12;
    p.bracoD.rotation.z = 0.35 * ent;
  }

  // piscar a cada ~3,7s
  const pisca = (t % 3.7) < 0.12 ? 0.12 : 1;
  for (const o of p.olhos) {
    o.branco.scale.set(olhoEsc, olhoEsc * pisca, 1);
    o.pupila.scale.set(olhoEsc, olhoEsc * pisca, 1);
    o.pupila.position.x = o.x0 + olharX;
    o.pupila.position.y = 0.58 + olharY;
    o.sobr.position.y = sobrY;
    o.sobr.rotation.z = sobrRot * -o.lado;
  }
  // boca: abre nas palavras faladas; "surpreso" deixa um "O"
  let abre = falando ? 0.35 + 0.65 * Math.abs(Math.sin(t * 17)) : 0;
  if (acao === "surpreso" && tl < 1.0) abre = Math.max(abre, 0.9);
  p.boca.scale.set(acao === "surpreso" ? 0.7 : 1, 1 + abre * 3.2, 1);
}

function posarBit(p, humor, tl, t) {
  p.corpo.position.set(0, 0.12 + Math.sin(t * 2.6) * 0.07, 0);
  p.corpo.rotation.set(0, Math.sin(t * 0.8) * 0.2, Math.sin(t * 1.3) * 0.04);
  const cor = humor === "medo" ? "#ff4d4d" : "#ffd23f";
  p.lampada.material.color.set(cor); p.lampada.material.emissive.set(cor);
  p.lampada.material.emissiveIntensity = 2 + Math.sin(t * 6) * 0.8;
  const pisca = (t % 4.3) < 0.1 ? 0.15 : 1;
  for (const o of p.olhos) {
    if (humor === "comemora" || humor === "surpreso") o.scale.set(1.25, 1.3 * pisca, 1);
    else if (humor === "medo") o.scale.set(0.8, 0.5 * pisca, 1);
    else o.scale.set(1, pisca, 1);
  }
  p.boca.scale.set(humor === "surpreso" ? 0.5 : 1, humor === "surpreso" ? 4 : 1, 1);
  if (humor === "comemora") p.corpo.position.y += Math.abs(Math.sin(tl * 7)) * 0.4;
}

// ---------- objetos ----------

function lowpoly(raio, cor, detalhe = 1, rugoso = 0.08, seed = 1) {
  const geo = new THREE.IcosahedronGeometry(raio, detalhe);
  const r = semente(seed), pos = geo.attributes.position, v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).multiplyScalar(1 + (r() - 0.5) * rugoso);
    pos.setXYZ(i, v.x, v.y, v.z);
  }
  geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, mat(cor, { flatShading: true }));
  m.castShadow = m.receiveShadow = true;
  return m;
}

function planeta(raio, mar, terra, seed) {  // esfera low-poly com "continentes" pintados por vértice
  const geo = new THREE.IcosahedronGeometry(raio, 3).toNonIndexed();
  const r = semente(seed), cores = [], c1 = new THREE.Color(mar), c2 = new THREE.Color(terra);
  const sementes = Array.from({ length: 7 }, () => new THREE.Vector3(r() - 0.5, r() - 0.5, r() - 0.5).normalize());
  const pos = geo.attributes.position, v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i += 3) {
    v.fromBufferAttribute(pos, i).normalize();
    const continente = sementes.some((s) => s.dot(v) > 0.78);
    const c = continente ? c2 : c1;
    for (let k = 0; k < 3; k++) cores.push(c.r, c.g, c.b);
  }
  geo.setAttribute("color", new THREE.Float32BufferAttribute(cores, 3));
  geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 0.9 }));
  m.castShadow = m.receiveShadow = true;
  return m;
}

const OBJETOS = {
  terra: () => { const g = grupo(); g.add(planeta(1.1, "#2463d6", "#3fae4f", 3)); return g; },
  lua: () => { const g = grupo(); g.add(lowpoly(0.95, "#c9c6bd", 2, 0.12, 5)); return g; },
  sol: () => { const g = grupo(); g.add(lowpoly(1.2, "#ffb703", 2, 0.05, 9));
               g.children[0].material = luz("#ffae00", 1.6); return g; },
  foguete: () => {
    const g = grupo();
    caixa(0.6, 1.5, 0.6, "#eeeeee", 0, 0.75, 0, g);
    caixa(0.42, 0.42, 0.42, "#e63946", 0, 1.7, 0, g).rotation.y = Math.PI / 4;
    caixa(0.26, 0.26, 0.07, luz("#7fd1ff", 1.2), 0, 1.0, 0.31, g);
    for (const a of [0, Math.PI / 2, Math.PI, 1.5 * Math.PI]) {
      const f = caixa(0.1, 0.5, 0.4, "#e63946", Math.sin(a) * 0.35, 0.25, Math.cos(a) * 0.35, g);
      f.rotation.y = a;
    }
    g.userData.chama = caixa(0.36, 0.5, 0.36, luz("#ff7b00", 3), 0, -0.25, 0, g);
    return g;
  },
  predio: () => {
    const g = grupo();
    caixa(1.0, 2.6, 1.0, "#3a3f6b", 0, 1.3, 0, g);
    const r = semente(11);
    for (let y = 0; y < 6; y++) for (let x = 0; x < 3; x++)
      if (r() > 0.3) caixa(0.16, 0.2, 0.03, luz(r() > 0.5 ? "#ffd27a" : "#9fd9ff", 1.5), -0.28 + x * 0.28, 0.4 + y * 0.38, 0.51, g);
    return g;
  },
  carro: () => {
    const g = grupo();
    caixa(1.7, 0.45, 0.85, "#e63946", 0, 0.45, 0, g);
    caixa(0.95, 0.4, 0.8, "#e63946", -0.1, 0.88, 0, g);
    caixa(0.85, 0.3, 0.82, luz("#9fd9ff", 0.6), -0.1, 0.9, 0, g);
    for (const x of [-0.55, 0.55]) for (const z of [-0.43, 0.43]) caixa(0.36, 0.36, 0.14, "#15151f", x, 0.2, z, g);
    caixa(0.06, 0.12, 0.2, luz("#fff3b0", 2.5), 0.86, 0.5, 0.25, g);
    caixa(0.06, 0.12, 0.2, luz("#fff3b0", 2.5), 0.86, 0.5, -0.25, g);
    return g;
  },
  arvore: () => {
    const g = grupo();
    caixa(0.32, 1.1, 0.32, "#6b4423", 0, 0.55, 0, g);
    caixa(1.2, 0.8, 1.2, "#2f9e44", 0, 1.4, 0, g);
    caixa(0.8, 0.6, 0.8, "#40c057", 0, 1.95, 0, g);
    return g;
  },
  dinheiro: () => {
    const g = grupo();
    for (let i = 0; i < 5; i++) caixa(1.0, 0.12, 0.5, "#69db7c", 0, 0.06 + i * 0.13, (i % 2) * 0.05, g);
    for (let i = 0; i < 3; i++) {
      const m = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.08, 16), mat("#fcc419", { metalness: 0.6, roughness: 0.35 }));
      m.position.set(-0.6 + i * 0.6, 0.85 + i * 0.09, 0.2); m.rotation.x = Math.PI / 2; m.castShadow = true; g.add(m);
    }
    return g;
  },
  celular: () => {
    const g = grupo();
    caixa(0.9, 1.7, 0.1, "#e83f6f", 0, 0.85, 0, g);
    caixa(0.78, 1.48, 0.02, "#151530", 0, 0.88, 0.06, g);
    const cores = ["#ffd23f", "#5cf2e3", "#ff7b54", "#a78bfa", "#69db7c", "#ff5c8a"];
    for (let i = 0; i < 9; i++) caixa(0.18, 0.18, 0.02, luz(cores[i % 6], 1.2), -0.24 + (i % 3) * 0.24, 1.3 - Math.floor(i / 3) * 0.26, 0.075, g);
    return g;
  },
  relogio: () => {
    const g = grupo();
    const aro = new THREE.Mesh(new THREE.CylinderGeometry(0.85, 0.85, 0.16, 24), mat("#f1f3f5"));
    aro.rotation.x = Math.PI / 2; aro.position.y = 1; aro.castShadow = true; g.add(aro);
    caixa(0.06, 0.5, 0.04, "#212529", 0, 1.2, 0.1, g);
    g.userData.ponteiro = grupo(0, 1, 0.12, g);
    caixa(0.05, 0.62, 0.03, "#e03131", 0, 0.28, 0, g.userData.ponteiro);
    return g;
  },
  meteoro: () => {
    const g = grupo();
    g.add(lowpoly(0.8, "#6c5f55", 1, 0.3, 21));
    g.userData.chama = caixa(0.9, 0.9, 1.6, luz("#ff6a00", 2.2), 0.25, 0.25, -0.9, g);
    return g;
  },
  pergunta: () => {  // "?" de blocos
    const g = grupo(), c = luz("#ffd23f", 1.1);
    for (const [x, y] of [[-0.3, 1.9], [0, 2.1], [0.3, 1.9], [0.38, 1.6], [0.15, 1.35], [0, 1.1], [0, 0.85], [0, 0.4]])
      caixa(0.28, 0.28, 0.28, c, x, y, 0, g);
    return g;
  },
};

function animarObjeto(obj, nome, tl, t) {
  const pop = elastico(tl / 0.6);
  obj.scale.setScalar(Math.max(pop, 0.001) * (obj.userData.escala || 1));
  obj.rotation.y = obj.userData.plano ? Math.sin(t * 1.2) * 0.25 - 0.2 : (obj.userData.giro ?? 0.4) * t;
  obj.position.y = (obj.userData.y0 || 0) + Math.sin(t * 1.8) * 0.08;
  if (nome === "foguete") {
    obj.userData.chama.scale.y = 0.8 + Math.abs(Math.sin(t * 30)) * 0.6;
    obj.position.y += Math.max(0, tl - 1.2) * 1.5;
    obj.rotation.y = t * 0.6;
  }
  if (nome === "relogio") obj.userData.ponteiro.rotation.z = -t * 3;
  if (nome === "meteoro") { obj.rotation.x = t * 0.7; obj.userData.chama.scale.z = 0.8 + Math.abs(Math.sin(t * 25)) * 0.4; }
}

// ---------- cenários ----------

function ceuGradiente(topo, base) {
  const c = document.createElement("canvas"); c.width = 2; c.height = 512;
  const g = c.getContext("2d"), gr = g.createLinearGradient(0, 0, 0, 512);
  gr.addColorStop(0, topo); gr.addColorStop(1, base);
  g.fillStyle = gr; g.fillRect(0, 0, 2, 512);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function estrelas(qtd, raio, seed, tamanho = 0.5, todoCeu = false) {
  const r = semente(seed), pos = [];
  for (let i = 0; i < qtd; i++) {
    const y = todoCeu ? r() - 0.5 : r() * 0.9 - 0.1;
    const v = new THREE.Vector3(r() - 0.5, y, r() - 0.5).normalize().multiplyScalar(raio);
    pos.push(v.x, v.y, v.z);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  return new THREE.Points(geo, new THREE.PointsMaterial({ color: "#ffffff", size: tamanho, sizeAttenuation: true }));
}

function luzes(g, { amb = "#8090ff", chao = "#1a1030", forca = 1.1, sol = "#cfd8ff", solForca = 2.2, solPos = [6, 12, 8],
                    contorno = "#5cf2e3" } = {}) {
  g.add(new THREE.HemisphereLight(amb, chao, forca));
  const d = new THREE.DirectionalLight(sol, solForca);
  d.position.set(...solPos);
  d.castShadow = true;
  d.shadow.mapSize.set(2048, 2048);
  Object.assign(d.shadow.camera, { left: -10, right: 10, top: 12, bottom: -6, near: 1, far: 60 });
  d.shadow.bias = -0.0008;
  g.add(d);
  const recorte = new THREE.DirectionalLight(contorno, 2.6);  // contorno colorido nas bordas dos blocos
  recorte.position.set(-4, 6, -9);
  g.add(recorte);
  const preenche = new THREE.DirectionalLight("#ffffff", 0.7);
  preenche.position.set(0, 3, 10);
  g.add(preenche);
}

const CENARIOS = {
  cidade_noite() {
    const g = grupo();
    g.userData.fundo = ceuGradiente("#0b0d2e", "#2a1f5c");
    g.userData.neblina = ["#1b1745", 18, 70];
    luzes(g, { amb: "#8d93ff", chao: "#1d1440", forca: 1.4, sol: "#d6dcff", solForca: 2.4, contorno: "#ff5cc8" });
    g.add(estrelas(900, 160, 2, 0.6));
    const chao = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), mat("#14123a", { roughness: 0.95 }));
    chao.rotation.x = -Math.PI / 2; chao.receiveShadow = true; g.add(chao);
    const grade = new THREE.GridHelper(200, 100, "#5b4bff", "#2c2670"); grade.position.y = 0.01; g.add(grade);
    // prédios ao fundo, com janelas acesas
    const r = semente(42), janela = [luz("#ffd27a", 1.4), luz("#9fd9ff", 1.2), luz("#ffffff", 0.9)];
    for (let i = 0; i < 46; i++) {
      const lado = i % 2 ? 1 : -1;
      const x = lado * (3 + r() * 22), z = -6 - r() * 40, w = 1.5 + r() * 2.2, h = 3 + r() * 13, d = 1.5 + r() * 2;
      const p = caixa(w, h, d, r() > 0.5 ? "#232456" : "#2d2b66", x, h / 2, z, g);
      p.castShadow = false;
      for (let y = 0.8; y < h - 0.5; y += 0.75) for (let k = -w / 2 + 0.35; k < w / 2 - 0.2; k += 0.45)
        if (r() > 0.55) caixa(0.22, 0.3, 0.03, janela[Math.floor(r() * 3)], x + k, y, z + d / 2 + 0.02, g).castShadow = false;
    }
    const lua = lowpoly(4, "#f1e9d0", 2, 0.05, 8); lua.material = luz("#f6eed5", 0.9); lua.position.set(-14, 26, -70); g.add(lua);
    return g;
  },

  espaco() {
    const g = grupo();
    g.userData.fundo = ceuGradiente("#02020a", "#120a2e");
    luzes(g, { amb: "#7a7cff", chao: "#0a0620", forca: 0.9, sol: "#fff1d6", solForca: 3.2, solPos: [10, 6, 6], contorno: "#5cf2e3" });
    g.add(estrelas(2400, 150, 5, 0.55, true));
    const terra = planeta(7, "#2463d6", "#3fae4f", 13); terra.position.set(-9, 9, -42); g.add(terra);
    g.userData.planeta = terra;
    const pedras = semente(77);
    for (let i = 0; i < 14; i++) {
      const p = lowpoly(0.2 + pedras() * 0.5, "#8a8178", 0, 0.4, 100 + i);
      p.position.set((pedras() - 0.5) * 24, pedras() * 10 - 2, -5 - pedras() * 20); g.add(p);
    }
    return g;
  },

  estudio() {  // quarto à noite com janela pra cidade, mesa e prateleira
    const g = grupo();
    g.userData.fundo = ceuGradiente("#1a1238", "#1a1238");
    luzes(g, { amb: "#b3aeff", chao: "#3a2440", forca: 1.5, sol: "#ffe2b8", solForca: 2.2, solPos: [-4, 9, 7], contorno: "#ffb86b" });
    const ponto = new THREE.PointLight("#ffb86b", 25, 14); ponto.position.set(2.4, 3.6, 1.5); g.add(ponto);
    caixa(30, 0.2, 14, "#3b2a4a", 0, -0.1, -2, g);                                // chão
    caixa(30, 10, 0.3, "#2b2350", 0, 5, -4.5, g);                                 // parede
    caixa(5.4, 3.4, 0.1, "#0c0a24", -3.2, 4.6, -4.3, g);                          // janela
    const r = semente(5);
    for (let i = 0; i < 70; i++) caixa(0.12, 0.16, 0.02, luz(r() > 0.4 ? "#ffd27a" : "#9fd9ff", 1.3),
                                      -5.6 + r() * 4.8, 3.1 + r() * 2.9, -4.22, g);
    for (const [x, y, w, h] of [[-3.2, 6.35, 5.6, 0.18], [-3.2, 2.85, 5.6, 0.18], [-6.0, 4.6, 0.18, 3.6], [-0.4, 4.6, 0.18, 3.6], [-3.2, 4.6, 0.12, 3.4]])
      caixa(w, h, 0.25, "#4a3a6e", x, y, -4.2, g);
    caixa(3.6, 0.2, 0.18, "#5b4a3a", 4.2, 5.4, -4.2, g);                          // prateleira
    for (let i = 0; i < 6; i++) caixa(0.3, 0.6 + r() * 0.3, 0.5, ["#e63946", "#ffd23f", "#5cf2e3", "#a78bfa"][i % 4], 2.8 + i * 0.5, 5.8, -4.1, g);
    caixa(3.2, 0.16, 1.4, "#6b4f3a", 3.2, 1.6, -2.6, g);                          // mesa
    for (const x of [1.8, 4.6]) caixa(0.16, 1.6, 1.2, "#5a4232", x, 0.8, -2.6, g);
    caixa(1.4, 0.9, 0.08, "#16162e", 3.0, 2.25, -2.9, g);                         // monitor
    caixa(1.25, 0.75, 0.02, luz("#3d5afe", 0.9), 3.0, 2.25, -2.85, g);
    caixa(0.3, 0.6, 0.3, "#ffd23f", 4.2, 1.98, -2.5, g);                          // luminária
    caixa(0.5, 0.2, 0.5, luz("#fff3c4", 2.2), 4.2, 2.35, -2.5, g);
    // quadro de cortiça com papeizinhos
    caixa(2.0, 1.5, 0.08, "#b07d4f", 4.3, 3.6, -4.25, g);
    for (let i = 0; i < 5; i++) caixa(0.4, 0.4, 0.02, ["#fff3b0", "#ffd6e7", "#c3fae8"][i % 3], 3.6 + (i % 3) * 0.6, 3.9 - Math.floor(i / 3) * 0.6, -4.2, g);
    return g;
  },
  campo() {  // fazenda ao pôr do sol: plantação, celeiro, cerca e árvores
    const g = grupo();
    g.userData.fundo = ceuGradiente("#3d5a99", "#ffb48a");
    g.userData.neblina = ["#f2b38f", 25, 90];
    luzes(g, { amb: "#ffd9b0", chao: "#4a6a2a", forca: 1.4, sol: "#ffcf8a", solForca: 2.8, solPos: [-8, 7, 6], contorno: "#ff8a5c" });
    caixa(200, 0.2, 200, "#5c9e3a", 0, -0.1, -40, g);
    const r = semente(31);
    for (let fila = 0; fila < 9; fila++) for (let k = 0; k < 16; k++)          // plantação em fileiras
      caixa(0.5, 0.35 + r() * 0.25, 0.5, r() > 0.15 ? "#8bc34a" : "#ffd23f", -16 + k * 1.1, 0.2, -7 - fila * 1.4, g).castShadow = false;
    for (let x = -12; x <= 12; x += 1.3) caixa(0.14, 0.7, 0.14, "#8d6e63", x, 0.35, 2.6, g);   // cerca
    caixa(26, 0.1, 0.08, "#8d6e63", 0, 0.55, 2.6, g);
    caixa(5, 3.4, 4, "#c0392b", 7.5, 1.7, -14, g);                               // celeiro
    const telhado = caixa(5.6, 0.4, 3.2, "#5d4037", 7.5, 3.7, -15.2, g); telhado.rotation.x = 0.55;
    const telhado2 = caixa(5.6, 0.4, 3.2, "#5d4037", 7.5, 3.7, -12.8, g); telhado2.rotation.x = -0.55;
    caixa(1.4, 2, 0.1, "#f4ead2", 7.5, 1.0, -11.95, g);
    for (const [x, z, s] of [[-6, -9, 1.3], [-9, -16, 1.6], [12, -8, 1.2], [-3.5, -22, 1.8], [3, -26, 1.5]]) {
      caixa(0.4 * s, 1.4 * s, 0.4 * s, "#6b4423", x, 0.7 * s, z, g);
      caixa(1.6 * s, 1.2 * s, 1.6 * s, "#2f9e44", x, 1.9 * s, z, g);
    }
    const sol = lowpoly(5, "#ffd27a", 2, 0.03, 4); sol.material = luz("#ffcf6a", 1.4); sol.position.set(-22, 9, -80); g.add(sol);
    return g;
  },

  oceano() {  // ilhota de areia no mar, coqueiro e barco ao longe
    const g = grupo();
    g.userData.fundo = ceuGradiente("#2b6cb0", "#a7e0ff");
    g.userData.neblina = ["#9fd3f0", 30, 110];
    luzes(g, { amb: "#cfe9ff", chao: "#1c5d8a", forca: 1.5, sol: "#fff4d6", solForca: 2.8, solPos: [8, 12, 6], contorno: "#ffffff" });
    const mar = new THREE.Mesh(new THREE.PlaneGeometry(300, 300), mat("#1e7fc2", { roughness: 0.35, metalness: 0.1 }));
    mar.rotation.x = -Math.PI / 2; mar.position.y = -0.35; mar.receiveShadow = true; g.add(mar);
    caixa(7, 0.6, 5, "#f2d49b", -0.3, -0.25, 0, g);                              // ilhota
    caixa(0.35, 3.2, 0.35, "#8d6e63", -2.6, 1.6, -1.2, g).rotation.z = 0.12;      // coqueiro
    for (let i = 0; i < 5; i++) {
      const folha = caixa(2.2, 0.12, 0.6, "#2f9e44", -2.4, 3.2, -1.2, g);
      folha.rotation.y = i * 1.25; folha.rotation.z = -0.35; folha.translateX(0.9);
    }
    const r = semente(9);
    g.userData.ondas = [];
    for (let i = 0; i < 40; i++) {
      const o = caixa(0.6 + r() * 1.2, 0.08, 0.2, "#e3f6ff", (r() - 0.5) * 50, -0.3, -4 - r() * 50, g);
      o.castShadow = false; g.userData.ondas.push([o, r() * 6]);
    }
    caixa(3, 0.8, 1.2, "#f4f4f4", 14, 0.1, -40, g); caixa(1.4, 0.8, 1, "#e63946", 14, 0.9, -40, g);   // barco
    return g;
  },
};

// ---------- câmeras ----------

// Cada plano: [posição inicial, posição final, alvo]. O personagem fica em x≈-0.6 e o destaque em x≈+1.3.
const CAMERAS = {
  frente: [[0.25, 3.0, 10.0], [0.25, 2.95, 8.8], [0.25, 2.9, 0]],
  close: [[-0.5, 2.95, 5.4], [-0.5, 2.95, 4.6], [-0.5, 3.05, 0]],
  aberto: [[0, 6.5, 19], [0, 5.8, 15.5], [0, 4.6, -4]],
  baixo: [[0.3, 1.0, 8.2], [0.3, 1.2, 7.4], [0.2, 3.3, 0]],
  orbita: null,
  destaque: [[1.0, 2.6, 7.2], [1.1, 2.5, 6.0], [1.1, 2.4, 0]],
};

function posicionarCamera(nome, tl, dur, t) {
  const k = suave(tl / Math.max(dur, 0.1));
  let pos, alvo;
  if (nome === "orbita") {
    const a = -0.5 + k * 1.0;
    pos = new THREE.Vector3(Math.sin(a) * 9.5, 3.1, Math.cos(a) * 9.5);
    alvo = new THREE.Vector3(0.2, 2.9, 0);
  } else {
    const [p0, p1, al] = CAMERAS[nome] || CAMERAS.frente;
    pos = new THREE.Vector3(lerp(p0[0], p1[0], k), lerp(p0[1], p1[1], k), lerp(p0[2], p1[2], k));
    alvo = new THREE.Vector3(...al);
  }
  // leve "câmera na mão"
  pos.x += Math.sin(t * 0.9) * 0.05; pos.y += Math.sin(t * 1.3) * 0.04;
  camera.position.copy(pos);
  camera.lookAt(alvo);
}

// ---------- HUD ----------

const $ = (id) => document.getElementById(id);
const faixa = $("faixa"), contador = $("contador"), legenda = $("legenda"), corte = $("corte");

function formatarNumero(n, casas) {
  return n.toLocaleString(SB.lang === "en" ? "en-US" : "pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}

function blocosLegenda(palavras) {  // até 3 palavras por bloco, quebrando na pontuação
  const blocos = []; let atual = [];
  for (const p of palavras) {
    atual.push(p);
    if (atual.length === 3 || /[.,!?;:]$/.test(p.palavra)) { blocos.push(atual); atual = []; }
  }
  if (atual.length) blocos.push(atual);
  return blocos;
}

function desenharHud(t, cena, tl) {
  if (cena.texto_topo) {
    faixa.style.display = "block";
    const txt = cena.texto_topo.texto || "", d = cena.texto_topo.destaque || "";
    const html = d && txt.toUpperCase().includes(d.toUpperCase())
      ? txt.toUpperCase().replace(d.toUpperCase(), `<span class="d">${d.toUpperCase()}</span>`) : txt.toUpperCase();
    if (faixa.dataset.html !== html) { faixa.innerHTML = html; faixa.dataset.html = html; }
    const e = elastico(tl / 0.5);
    faixa.style.transform = `translateX(-50%) rotate(-1.2deg) scale(${0.6 + 0.4 * e})`;
    faixa.style.opacity = clamp01(tl / 0.15);
  } else faixa.style.display = "none";

  if (cena.contador) {
    const c = cena.contador;
    contador.style.display = "block";
    const k = suave(tl / Math.max((cena.fim - cena.inicio) * 0.7, 0.3));
    const valor = lerp(c.de ?? 0, c.ate, k);
    contador.querySelector(".n").textContent = (c.prefixo || "") + formatarNumero(valor, c.casas || 0) + (c.sufixo || "");
    contador.querySelector(".r").textContent = c.rotulo || "";
    contador.style.transform = `translateX(-50%) scale(${0.5 + 0.5 * elastico(tl / 0.5)})`;
  } else contador.style.display = "none";

  // legenda: bloco que contém o instante t
  let bloco = null;
  for (let i = 0; i < BLOCOS.length; i++) {
    const fim = i + 1 < BLOCOS.length ? BLOCOS[i + 1][0].inicio : BLOCOS[i][BLOCOS[i].length - 1].fim + 0.5;
    if (t >= BLOCOS[i][0].inicio && t < fim) { bloco = BLOCOS[i]; break; }
  }
  const html = bloco ? bloco.map((p) => {
    const atual = t >= p.inicio && (t < p.fim || p === bloco[bloco.length - 1]);
    return `<span class="${atual ? "atual" : ""}">${p.palavra.replace(/[,;:]$/, "")}</span>`;
  }).join(" ") : "";
  if (legenda.dataset.html !== html) { legenda.innerHTML = html; legenda.dataset.html = html; }
}

// ---------- montagem ----------

let SB = null, BLOCOS = [], CENAS = [], ATORES = {};

window.preparar = async (storyboard) => {
  SB = storyboard;
  // O 3D pode ser desenhado em resolução menor e esticado (na nuvem é na CPU); o texto do HUD continua nítido
  const esc = SB.escala_3d || 1;
  renderer.setSize(Math.round(W * esc), Math.round(H * esc), false);
  renderer.domElement.style.width = W + "px"; renderer.domElement.style.height = H + "px";
  await document.fonts.load('88px "Archivo"');
  BLOCOS = blocosLegenda(SB.palavras || []);
  const usados = new Set(SB.cenas.map((c) => c.cenario));
  const cenarios = {};
  for (const nome of usados) {
    const g = (CENARIOS[nome] || CENARIOS.estudio)();
    g.visible = false; scene.add(g); cenarios[nome] = g;
  }
  ATORES.explorador = criarExplorador(); scene.add(ATORES.explorador.raiz);
  ATORES.bit = criarBit(); scene.add(ATORES.bit.raiz);
  CENAS = SB.cenas.map((c, i) => {
    const obj = c.objeto && OBJETOS[c.objeto] ? OBJETOS[c.objeto]() : null;
    if (obj) {
      const esfera = ["terra", "lua", "sol", "meteoro"].includes(c.objeto);
      const grande = esfera && c.cenario === "espaco";
      obj.position.set(grande ? 1.25 : 1.35, grande ? 4.7 : (esfera ? 2.3 : 0), grande ? -3 : 0.6);
      obj.userData.y0 = obj.position.y;
      obj.userData.plano = ["relogio", "celular", "dinheiro", "pergunta", "predio"].includes(c.objeto);
      obj.userData.escala = grande ? 1.25 : (esfera ? 0.7 : 0.85);
      obj.visible = false; scene.add(obj);
    }
    return { ...c, n: i, grupo: cenarios[c.cenario], obj };
  });
  return SB.duracao;
};

window.quadro = (t) => {
  let cena = CENAS[CENAS.length - 1];
  for (const c of CENAS) if (t >= c.inicio && t < c.fim) { cena = c; break; }
  const tl = t - cena.inicio, dur = cena.fim - cena.inicio;

  for (const c of CENAS) { c.grupo.visible = false; if (c.obj) c.obj.visible = false; }
  cena.grupo.visible = true;
  scene.background = cena.grupo.userData.fundo;
  const nb = cena.grupo.userData.neblina;
  scene.fog = nb ? new THREE.Fog(nb[0], nb[1], nb[2]) : null;
  if (cena.grupo.userData.planeta) cena.grupo.userData.planeta.rotation.y = t * 0.03;
  for (const [o, fase] of cena.grupo.userData.ondas || []) o.position.y = -0.3 + Math.sin(t * 1.6 + fase) * 0.06;

  // explorador sempre em cena; Bit aparece quando não há objeto no lugar dele
  const ex = ATORES.explorador, bit = ATORES.bit;
  const falando = (SB.palavras || []).some((p) => t >= p.inicio && t < p.fim);
  const flutua = cena.cenario === "espaco";
  ex.raiz.position.set(-0.6, flutua ? 0.9 + Math.sin(t * 1.2) * 0.15 : 0, 0);
  ex.raiz.rotation.set(flutua ? Math.sin(t * 0.7) * 0.08 : 0, 0.18, flutua ? Math.sin(t * 0.9) * 0.06 : 0);
  if (cena.acao === "anda") ex.raiz.position.x = lerp(-2.6, -0.6, suave(tl / Math.min(dur, 1.6)));
  posarExplorador(ex, cena.acao || "fala", tl, t, falando, dur);

  bit.raiz.visible = !cena.obj && cena.bit !== false;
  bit.raiz.position.set(1.45, flutua ? 1.2 : 0, 0.5);
  bit.raiz.rotation.y = -0.35;
  posarBit(bit, cena.acao, tl, t);
  if (cena.obj) { cena.obj.visible = true; animarObjeto(cena.obj, cena.objeto, tl, t); }

  posicionarCamera(cena.camera || "frente", tl, dur, t);

  // corte: 0,1s de escuro nas trocas de cena
  const ate = Math.min(tl, cena.fim - t);
  corte.style.opacity = cena.n > 0 && tl < 0.09 ? 1 - tl / 0.09 : (ate < 0.05 && cena.n < CENAS.length - 1 ? 0.6 : 0);

  desenharHud(t, cena, tl);
  renderer.render(scene, camera);
};

window.pronto = true;
