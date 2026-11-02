// Estúdio 3D (v2, "cinema"): monta cada plano a partir do storyboard e desenha qualquer instante t.
// Determinístico: o mesmo t sempre gera o mesmo quadro (o Python grava quadro a quadro).
//
//   window.preparar(storyboard)  → monta cenários, elenco e personagens (devolve a duração)
//   window.quadro(t)             → desenha o instante t
//
// Cada plano mostra o ASSUNTO da fala: "elenco" = modelos da biblioteca (ou criados pela IA no roteiro)
// com quantidade, lugar e movimento (enxame, voa, cai, some...). O explorador entra quando o plano pede.
import * as THREE from "three";
import { EffectComposer } from "./vendor/postprocessing/EffectComposer.js";
import { RenderPass } from "./vendor/postprocessing/RenderPass.js";
import { ShaderPass } from "./vendor/postprocessing/ShaderPass.js";
import { UnrealBloomPass } from "./vendor/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "./vendor/postprocessing/OutputPass.js";
import { BokehPass } from "./vendor/postprocessing/BokehPass.js";
import { RoundedBoxGeometry } from "./vendor/geometries/RoundedBoxGeometry.js";
import { MODELOS, PALETA, PELES, CABELOS } from "./modelos.js";

const W = 1080, H = 1920;
const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById("tela"), antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.02;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, W / H, 0.1, 400);

// ---------- pós-produção de cinema: foco, brilho, cor, vinheta, grão ----------

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const foco = new BokehPass(scene, camera, { focus: 6, aperture: 0.00028, maxblur: 0.0065 });
composer.addPass(foco);
const brilho = new UnrealBloomPass(new THREE.Vector2(W, H), 0.42, 0.5, 0.93);
composer.addPass(brilho);
composer.addPass(new OutputPass());
const grade = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, tempo: { value: 0 }, vinheta: { value: 0.42 }, quente: { value: 0.0 } },
  vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
  fragmentShader: `
    uniform sampler2D tDiffuse; uniform float tempo; uniform float vinheta; uniform float quente; varying vec2 vUv;
    void main() {
      vec2 d = vUv - 0.5; float r2 = dot(d, d);
      vec3 c = vec3(texture2D(tDiffuse, vUv + d * 0.006 * r2).r, texture2D(tDiffuse, vUv).g, texture2D(tDiffuse, vUv - d * 0.006 * r2).b);
      float l = dot(c, vec3(0.299, 0.587, 0.114));
      c = mix(c, c * vec3(0.9, 1.0, 1.1), (1.0 - l) * 0.28);              // sombras levemente azul-petróleo
      c = mix(c, c * vec3(1.08 + quente, 1.0, 0.9 - quente), l * 0.22);   // luzes âmbar
      c = (c - 0.5) * 1.07 + 0.5;                                          // contraste
      c *= 1.0 - vinheta * smoothstep(0.08, 0.55, r2);                     // vinheta
      float n = fract(sin(dot(vUv * vec2(12.9898, 78.233) + tempo, vec2(1.0))) * 43758.5453);
      c += (n - 0.5) * 0.03;                                               // grão de filme
      gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
    }`,
});
composer.addPass(grade);

function tamanhoRender(esc) {
  const w = Math.round(W * esc), h = Math.round(H * esc);
  renderer.setSize(w, h, false);
  renderer.domElement.style.width = W + "px"; renderer.domElement.style.height = H + "px";
  composer.setSize(w, h);
}
tamanhoRender(1);

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
const suave2 = (x) => { x = clamp01(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };  // ease in-out cúbico
const elastico = (x) => {
  x = clamp01(x);
  return x === 0 || x === 1 ? x : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * (2 * Math.PI) / 3) + 1;
};

const MATS = new Map();
function mat(cor, extra = {}) {
  const chave = cor + JSON.stringify(extra);
  if (!MATS.has(chave)) MATS.set(chave, new THREE.MeshStandardMaterial({ color: cor, roughness: 0.72, metalness: 0.03, ...extra }));
  return MATS.get(chave);
}
const luz = (cor, forca = 2.2) => mat(cor, { emissive: cor, emissiveIntensity: forca, roughness: 0.4 });
const vidro = (cor) => mat(cor, { transparent: true, opacity: 0.55, roughness: 0.1, metalness: 0.1 });

const GEOS = new Map();
function geoCaixa(w, h, d, redondo) {
  const chave = `${w}|${h}|${d}|${redondo}`;
  if (!GEOS.has(chave)) {
    const raio = Math.min(w, h, d) * 0.18;
    GEOS.set(chave, redondo && raio > 0.012 ? new RoundedBoxGeometry(w, h, d, 2, raio) : new THREE.BoxGeometry(w, h, d));
  }
  return GEOS.get(chave);
}
function caixa(w, h, d, material, x = 0, y = 0, z = 0, pai = null, redondo = false) {
  const m = new THREE.Mesh(geoCaixa(w, h, d, redondo), typeof material === "string" ? mat(material) : material);
  m.position.set(x, y, z);
  m.castShadow = true; m.receiveShadow = true;
  if (pai) pai.add(m);
  return m;
}
function grupo(x = 0, y = 0, z = 0, pai = null) {
  const g = new THREE.Group(); g.position.set(x, y, z);
  if (pai) pai.add(g);
  return g;
}

function lowpoly(raio, cor, detalhe = 1, rugoso = 0.08, seed = 1) {
  const geo = new THREE.IcosahedronGeometry(raio, detalhe);
  const r = semente(seed), pos = geo.attributes.position, v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i).multiplyScalar(1 + (r() - 0.5) * rugoso); pos.setXYZ(i, v.x, v.y, v.z); }
  geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, mat(cor, { flatShading: true }));
  m.castShadow = m.receiveShadow = true;
  return m;
}

function planeta(raio, mar, terra, seed) {
  const geo = new THREE.IcosahedronGeometry(raio, 3).toNonIndexed();
  const r = semente(seed), cores = [], c1 = new THREE.Color(mar), c2 = new THREE.Color(terra);
  const sementes = Array.from({ length: 7 }, () => new THREE.Vector3(r() - 0.5, r() - 0.5, r() - 0.5).normalize());
  const pos = geo.attributes.position, v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i += 3) {
    v.fromBufferAttribute(pos, i).normalize();
    const c = sementes.some((s) => s.dot(v) > 0.78) ? c2 : c1;
    for (let k = 0; k < 3; k++) cores.push(c.r, c.g, c.b);
  }
  geo.setAttribute("color", new THREE.Float32BufferAttribute(cores, 3));
  geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 0.85 }));
  m.castShadow = m.receiveShadow = true;
  return m;
}

// ---------- modelos da biblioteca ----------

function construirModelo(nome, def, r, extrasIA) {
  def = def || (extrasIA && extrasIA[nome]) || MODELOS.pergunta;
  const g = new THREE.Group(), interno = new THREE.Group();
  g.add(interno);
  const corVar = PALETA[Math.floor(r() * PALETA.length)], pele = PELES[Math.floor(r() * PELES.length)], cabelo = CABELOS[Math.floor(r() * CABELOS.length)];
  const partes = { asas: [], chamas: [] };
  const material = (cor, marca) => {
    if (marca === "var") return mat(corVar);
    if (marca === "pele") return mat(pele);
    if (marca === "cabelo") return mat(cabelo);
    if (marca === "brilho") return luz(cor, 1.6);
    if (marca === "chama") return luz(cor, 2.6);
    if (marca === "vidro") return vidro(cor);
    return mat(cor);
  };
  for (const [w, h, d, cor, x, y, z, marca] of [...(def.caixas || []), ...(def.extra || [])]) {
    const m = caixa(w, h, d, material(cor, marca), x, y, z, interno, true);
    if (marca === "asa") { m.userData.lado = Math.sign(x) || 1; partes.asas.push(m); }
    if (marca === "chama") partes.chamas.push(m);
  }
  if (def.esfera) {
    const e = def.esfera;
    const s = lowpoly(e.raio, e.cor, e.detalhe ?? 2, e.rugoso ?? 0.05, 7);
    if (e.brilho) s.material = luz(e.cor, e.brilho);
    interno.add(s);
  }
  if (def.planeta) interno.add(planeta(1, def.planeta.mar, def.planeta.terra, 13));
  if (def.anel) {
    const anel = new THREE.Mesh(new THREE.TorusGeometry(def.anel.raio, 0.18, 8, 48), luz(def.anel.cor, 2.4));
    anel.rotation.x = Math.PI / 2.4; interno.add(anel);
  }
  if (def.cilindro) {
    const c = def.cilindro;
    const m = new THREE.Mesh(new THREE.CylinderGeometry(c.raio, c.raio, c.altura, 24), mat(c.cor, { metalness: 0.6, roughness: 0.3 }));
    m.rotation.x = Math.PI / 2; m.castShadow = true; interno.add(m);
  }
  if (def.relogio) {
    const aro = new THREE.Mesh(new THREE.CylinderGeometry(0.85, 0.85, 0.16, 32), mat("#f1f3f5"));
    aro.rotation.x = Math.PI / 2; aro.castShadow = true; interno.add(aro);
    caixa(0.06, 0.45, 0.04, "#212529", 0, 0.2, 0.1, interno);
    partes.ponteiro = grupo(0, 0, 0.12, interno);
    caixa(0.05, 0.62, 0.03, "#e03131", 0, 0.28, 0, partes.ponteiro);
  }
  // normaliza: maior medida = tamanho; base no chão (modelos "chao") ou centro na origem
  const caixaB = new THREE.Box3().setFromObject(interno), med = new THREE.Vector3();
  caixaB.getSize(med);
  const esc = (def.tamanho || 1) / Math.max(med.x, med.y, med.z, 0.001);
  interno.scale.setScalar(esc);
  const centro = new THREE.Vector3(); caixaB.getCenter(centro);
  interno.position.set(-centro.x * esc, def.chao ? -caixaB.min.y * esc : -centro.y * esc, -centro.z * esc);
  g.userData = { partes, tamanho: def.tamanho || 1, chao: !!def.chao, altura: med.y * esc };
  return g;
}

// ---------- personagem ----------

function criarExplorador() {
  const p = {}, raiz = grupo(), corpo = grupo(0, 0, 0, raiz);
  p.raiz = raiz; p.corpo = corpo;
  const pele = "#c9875c", moletom = "#1fa39a", moletomEsc = "#178079", calca = "#252a4a", tenis = "#f1f1f1", cabelo = "#2a1a12";
  for (const lado of [-1, 1]) {
    const perna = grupo(0.22 * lado, 1.0, 0, corpo);
    caixa(0.38, 0.86, 0.42, calca, 0, -0.43, 0, perna, true);
    caixa(0.42, 0.2, 0.58, tenis, 0, -0.92, 0.06, perna, true);
    p[lado < 0 ? "pernaE" : "pernaD"] = perna;
  }
  const tronco = grupo(0, 1.0, 0, corpo); p.tronco = tronco;
  caixa(1.04, 1.02, 0.62, moletom, 0, 0.5, 0, tronco, true);
  caixa(0.7, 0.3, 0.06, moletomEsc, 0, 0.22, 0.33, tronco, true);
  caixa(0.06, 0.32, 0.05, "#f4f4f4", -0.13, 0.78, 0.33, tronco);
  caixa(0.06, 0.32, 0.05, "#f4f4f4", 0.13, 0.78, 0.33, tronco);
  caixa(0.9, 0.34, 0.3, moletomEsc, 0, 0.96, -0.3, tronco, true);
  for (const lado of [-1, 1]) {
    const braco = grupo(0.66 * lado, 0.92, 0, tronco);
    caixa(0.3, 0.84, 0.36, moletom, 0, -0.38, 0, braco, true);
    caixa(0.28, 0.26, 0.32, pele, 0, -0.9, 0, braco, true);
    p[lado < 0 ? "bracoE" : "bracoD"] = braco;
  }
  const cabeca = grupo(0, 1.05, 0, tronco); p.cabeca = cabeca;
  caixa(1.12, 1.0, 0.96, pele, 0, 0.52, 0, cabeca, true);
  caixa(1.2, 0.3, 1.04, cabelo, 0, 1.1, -0.02, cabeca, true);
  caixa(1.2, 0.62, 0.26, cabelo, 0, 0.78, -0.42, cabeca, true);
  caixa(0.18, 0.5, 0.9, cabelo, -0.6, 0.78, -0.05, cabeca, true);
  caixa(0.18, 0.5, 0.9, cabelo, 0.6, 0.78, -0.05, cabeca, true);
  const r = semente(7);
  for (let i = 0; i < 6; i++) caixa(0.22, 0.18 + r() * 0.16, 0.22, cabelo, -0.5 + i * 0.2, 0.93 - r() * 0.05, 0.42, cabeca, true);
  caixa(0.14, 0.14, 0.1, "#b87650", 0, 0.42, 0.52, cabeca, true);
  p.olhos = [];
  for (const lado of [-1, 1]) {
    const branco = caixa(0.26, 0.32, 0.04, "#ffffff", 0.25 * lado, 0.6, 0.49, cabeca);
    const pupila = caixa(0.13, 0.19, 0.03, "#141422", 0.25 * lado, 0.58, 0.515, cabeca);
    const brilhoOlho = caixa(0.035, 0.04, 0.02, mat("#ffffff"), 0.25 * lado + 0.03, 0.62, 0.53, cabeca);
    const sobr = caixa(0.32, 0.09, 0.05, cabelo, 0.25 * lado, 0.86, 0.49, cabeca);
    p.olhos.push({ branco, pupila, brilhoOlho, sobr, lado, x0: 0.25 * lado });
  }
  p.boca = caixa(0.32, 0.06, 0.03, "#3b1a1a", 0, 0.24, 0.49, cabeca);
  return p;
}

function posarExplorador(p, acao, tl, t, falando) {
  const ent = suave(tl / 0.35);
  p.corpo.position.set(0, Math.sin(t * 2.2) * 0.02, 0);
  p.tronco.rotation.set(0, 0, Math.sin(t * 1.1) * 0.015);
  p.cabeca.rotation.set(Math.sin(t * 1.7) * 0.03, Math.sin(t * 0.9) * 0.08, 0);
  for (const b of [p.bracoE, p.bracoD]) b.rotation.set(0, 0, 0);
  p.bracoE.rotation.z = -0.08; p.bracoD.rotation.z = 0.08;
  p.pernaE.rotation.x = 0; p.pernaD.rotation.x = 0;
  let olhoEsc = 1, sobrY = 0.86, sobrRot = 0, olharX = Math.sin(t * 0.6) * 0.02, olharY = 0;
  if (acao === "surpreso") {
    p.corpo.position.y += Math.max(0, Math.sin(clamp01(tl / 0.45) * Math.PI)) * 0.35;
    p.corpo.position.z = -0.25 * ent;
    p.bracoE.rotation.z = lerp(-0.08, -2.3, ent); p.bracoD.rotation.z = lerp(0.08, 2.3, ent);
    p.bracoE.rotation.x = p.bracoD.rotation.x = -0.3 * ent;
    olhoEsc = 1 + 0.35 * ent; sobrY = 0.86 + 0.1 * ent;
  } else if (acao === "aponta") {
    p.bracoD.rotation.z = lerp(0.08, 1.45, ent); p.bracoD.rotation.y = -0.2 * ent;
    p.tronco.rotation.y = 0.18 * ent; p.cabeca.rotation.y += 0.25 * ent; olharX = 0.04 * ent;
  } else if (acao === "pensa") {
    p.bracoD.rotation.x = -2.05 * ent; p.bracoD.rotation.z = -0.55 * ent;
    p.cabeca.rotation.z = 0.12 * ent; p.cabeca.rotation.x = -0.1 * ent;
    olharY = 0.05 * ent; olharX = 0.04 * ent; sobrRot = 0.12 * ent;
  } else if (acao === "comemora") {
    p.corpo.position.y += Math.abs(Math.sin(tl * 6.5)) * 0.32 * ent;
    p.bracoE.rotation.z = -2.6 * ent + Math.sin(tl * 13) * 0.15; p.bracoD.rotation.z = 2.6 * ent - Math.sin(tl * 13) * 0.15;
    sobrY = 0.9;
  } else if (acao === "medo") {
    p.corpo.position.x = Math.sin(t * 60) * 0.025 * ent; p.corpo.position.z = -0.2 * ent;
    p.bracoE.rotation.x = p.bracoD.rotation.x = -1.2 * ent;
    p.bracoE.rotation.z = -0.5 * ent; p.bracoD.rotation.z = 0.5 * ent;
    p.cabeca.rotation.x = 0.12 * ent; sobrRot = -0.3 * ent; olhoEsc = 1.2;
  } else if (acao === "acena") {
    p.bracoD.rotation.z = 2.5 * ent + Math.sin(tl * 9) * 0.35 * ent;
  } else if (acao === "anda") {
    const passo = Math.sin(tl * 7);
    p.pernaE.rotation.x = passo * 0.5; p.pernaD.rotation.x = -passo * 0.5;
    p.bracoE.rotation.x = -passo * 0.45; p.bracoD.rotation.x = passo * 0.45;
    p.corpo.position.y += Math.abs(Math.cos(tl * 7)) * 0.06;
  } else if (acao === "olha") {  // olha pro assunto, impressionado
    p.cabeca.rotation.y = 0.45 * ent; p.tronco.rotation.y = 0.2 * ent; olharX = 0.05 * ent; olhoEsc = 1.12;
  } else {  // fala
    p.bracoD.rotation.x = -0.5 * ent + Math.sin(t * 3) * 0.12; p.bracoD.rotation.z = 0.35 * ent;
  }
  const pisca = (t % 3.7) < 0.12 ? 0.12 : 1;
  for (const o of p.olhos) {
    o.branco.scale.set(olhoEsc, olhoEsc * pisca, 1);
    o.pupila.scale.set(olhoEsc, olhoEsc * pisca, 1);
    o.pupila.position.set(o.x0 + olharX, 0.58 + olharY, 0.515);
    o.brilhoOlho.position.set(o.x0 + olharX + 0.03, 0.62 + olharY, 0.53);
    o.brilhoOlho.visible = pisca === 1;
    o.sobr.position.y = sobrY; o.sobr.rotation.z = sobrRot * -o.lado;
  }
  let abre = falando ? 0.35 + 0.65 * Math.abs(Math.sin(t * 17)) : 0;
  if (acao === "surpreso" && tl < 1.0) abre = Math.max(abre, 0.9);
  p.boca.scale.set(acao === "surpreso" ? 0.7 : 1, 1 + abre * 3.2, 1);
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
    const v = new THREE.Vector3(r() - 0.5, todoCeu ? r() - 0.5 : r() * 0.9 - 0.1, r() - 0.5).normalize().multiplyScalar(raio);
    pos.push(v.x, v.y, v.z);
  }
  const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  return new THREE.Points(geo, new THREE.PointsMaterial({ color: "#ffffff", size: tamanho, sizeAttenuation: true }));
}

// poeira/vagalumes flutuando na luz: dá profundidade e "ar" de cinema
function particulas(cor, qtd, seed, tamanho = 0.06) {
  const r = semente(seed), base = [];
  for (let i = 0; i < qtd; i++) base.push([(r() - 0.5) * 16, r() * 7, -r() * 14 + 4, r() * 6.28]);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(qtd * 3), 3));
  const pts = new THREE.Points(geo, new THREE.PointsMaterial({ color: cor, size: tamanho, transparent: true, opacity: 0.85,
    blending: THREE.AdditiveBlending, depthWrite: false }));
  pts.userData.animar = (t) => {
    const a = geo.attributes.position.array;
    base.forEach(([x, y, z, f], i) => {
      a[i * 3] = x + Math.sin(t * 0.3 + f) * 0.4; a[i * 3 + 1] = (y + t * 0.12 + Math.sin(t * 0.5 + f) * 0.2) % 7; a[i * 3 + 2] = z;
    });
    geo.attributes.position.needsUpdate = true;
  };
  return pts;
}

function luzes(g, { amb = "#8090ff", chao = "#1a1030", forca = 1.1, sol = "#cfd8ff", solForca = 2.2, solPos = [6, 12, 8], contorno = "#5cf2e3" } = {}) {
  g.add(new THREE.HemisphereLight(amb, chao, forca));
  const d = new THREE.DirectionalLight(sol, solForca);
  d.position.set(...solPos); d.castShadow = true; d.shadow.mapSize.set(2048, 2048);
  Object.assign(d.shadow.camera, { left: -12, right: 12, top: 14, bottom: -6, near: 1, far: 70 });
  d.shadow.bias = -0.0006; d.shadow.radius = 4;
  g.add(d);
  const recorte = new THREE.DirectionalLight(contorno, 2.8); recorte.position.set(-4, 6, -9); g.add(recorte);
  const preenche = new THREE.DirectionalLight("#ffffff", 0.55); preenche.position.set(0, 3, 10); g.add(preenche);
}

const CENARIOS = {
  cidade_noite() {
    const g = grupo();
    g.userData.fundo = ceuGradiente("#0b0d2e", "#3a2a6e"); g.userData.neblina = ["#1f1a52", 16, 70];
    luzes(g, { amb: "#8d93ff", chao: "#1d1440", forca: 1.3, sol: "#d6dcff", solForca: 2.2, contorno: "#ff5cc8" });
    g.add(estrelas(900, 160, 2, 0.6));
    const chao = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), mat("#15133c", { roughness: 0.55, metalness: 0.2 }));
    chao.rotation.x = -Math.PI / 2; chao.receiveShadow = true; g.add(chao);
    const grade = new THREE.GridHelper(200, 100, "#5b4bff", "#2c2670"); grade.position.y = 0.01; g.add(grade);
    const r = semente(42), janela = [luz("#ffd27a", 1.6), luz("#9fd9ff", 1.4), luz("#ffffff", 1.0)];
    for (let i = 0; i < 46; i++) {
      const lado = i % 2 ? 1 : -1, x = lado * (3.5 + r() * 22), z = -7 - r() * 40, w = 1.5 + r() * 2.2, h = 3 + r() * 13, d = 1.5 + r() * 2;
      caixa(w, h, d, r() > 0.5 ? "#232456" : "#2d2b66", x, h / 2, z, g).castShadow = false;
      for (let y = 0.8; y < h - 0.5; y += 0.75) for (let k = -w / 2 + 0.35; k < w / 2 - 0.2; k += 0.45)
        if (r() > 0.55) caixa(0.22, 0.3, 0.03, janela[Math.floor(r() * 3)], x + k, y, z + d / 2 + 0.02, g).castShadow = false;
    }
    const lua = lowpoly(4, "#f1e9d0", 2, 0.05, 8); lua.material = luz("#f6eed5", 1.1); lua.position.set(-14, 26, -70); g.add(lua);
    g.add(particulas("#9fb4ff", 160, 3, 0.05));
    return g;
  },
  espaco() {
    const g = grupo();
    g.userData.fundo = ceuGradiente("#02020a", "#140b33"); g.userData.flutua = true;
    luzes(g, { amb: "#7a7cff", chao: "#0a0620", forca: 0.8, sol: "#fff1d6", solForca: 3.4, solPos: [10, 6, 6], contorno: "#5cf2e3" });
    g.add(estrelas(2600, 150, 5, 0.55, true));
    const terra = planeta(7, "#2463d6", "#3fae4f", 13); terra.position.set(-9, 9, -42); g.add(terra); g.userData.planeta = terra;
    const pedras = semente(77);
    for (let i = 0; i < 14; i++) {
      const p = lowpoly(0.2 + pedras() * 0.5, "#8a8178", 0, 0.4, 100 + i);
      p.position.set((pedras() - 0.5) * 24, pedras() * 10 - 2, -5 - pedras() * 20); g.add(p);
    }
    return g;
  },
  estudio() {
    const g = grupo();
    g.userData.fundo = ceuGradiente("#1a1238", "#1a1238");
    luzes(g, { amb: "#b3aeff", chao: "#3a2440", forca: 1.4, sol: "#ffe2b8", solForca: 2.2, solPos: [-4, 9, 7], contorno: "#ffb86b" });
    const ponto = new THREE.PointLight("#ffb86b", 25, 14); ponto.position.set(2.4, 3.6, 1.5); g.add(ponto);
    caixa(30, 0.2, 14, "#3b2a4a", 0, -0.1, -2, g); caixa(30, 10, 0.3, "#2b2350", 0, 5, -4.5, g);
    caixa(5.4, 3.4, 0.1, "#0c0a24", -3.2, 4.6, -4.3, g);
    const r = semente(5);
    for (let i = 0; i < 70; i++) caixa(0.12, 0.16, 0.02, luz(r() > 0.4 ? "#ffd27a" : "#9fd9ff", 1.5), -5.6 + r() * 4.8, 3.1 + r() * 2.9, -4.22, g);
    for (const [x, y, w, h] of [[-3.2, 6.35, 5.6, 0.18], [-3.2, 2.85, 5.6, 0.18], [-6.0, 4.6, 0.18, 3.6], [-0.4, 4.6, 0.18, 3.6], [-3.2, 4.6, 0.12, 3.4]])
      caixa(w, h, 0.25, "#4a3a6e", x, y, -4.2, g);
    caixa(3.6, 0.2, 0.18, "#5b4a3a", 4.2, 5.4, -4.2, g);
    for (let i = 0; i < 6; i++) caixa(0.3, 0.6 + r() * 0.3, 0.5, ["#e63946", "#ffd23f", "#5cf2e3", "#a78bfa"][i % 4], 2.8 + i * 0.5, 5.8, -4.1, g, true);
    caixa(3.2, 0.16, 1.4, "#6b4f3a", 3.2, 1.6, -2.6, g);
    for (const x of [1.8, 4.6]) caixa(0.16, 1.6, 1.2, "#5a4232", x, 0.8, -2.6, g);
    caixa(1.4, 0.9, 0.08, "#16162e", 3.0, 2.25, -2.9, g); caixa(1.25, 0.75, 0.02, luz("#3d5afe", 1.0), 3.0, 2.25, -2.85, g);
    caixa(0.3, 0.6, 0.3, "#ffd23f", 4.2, 1.98, -2.5, g, true); caixa(0.5, 0.2, 0.5, luz("#fff3c4", 2.4), 4.2, 2.35, -2.5, g, true);
    g.add(particulas("#ffd9a0", 120, 8, 0.04));
    return g;
  },
  campo() {
    const g = grupo();
    g.userData.fundo = ceuGradiente("#3d5a99", "#ffb48a"); g.userData.neblina = ["#f2b38f", 22, 90]; g.userData.quente = 0.05;
    luzes(g, { amb: "#ffd9b0", chao: "#4a6a2a", forca: 1.4, sol: "#ffcf8a", solForca: 3.0, solPos: [-8, 7, 6], contorno: "#ff8a5c" });
    caixa(200, 0.2, 200, "#5c9e3a", 0, -0.1, -40, g);
    const r = semente(31);
    for (let fila = 0; fila < 9; fila++) for (let k = 0; k < 16; k++)
      caixa(0.5, 0.35 + r() * 0.25, 0.5, r() > 0.15 ? "#8bc34a" : "#ffd23f", -16 + k * 1.1, 0.2, -8 - fila * 1.4, g, true).castShadow = false;
    caixa(5, 3.4, 4, "#c0392b", 9, 1.7, -16, g);
    const t1 = caixa(5.6, 0.4, 3.2, "#5d4037", 9, 3.7, -17.2, g); t1.rotation.x = 0.55;
    const t2 = caixa(5.6, 0.4, 3.2, "#5d4037", 9, 3.7, -14.8, g); t2.rotation.x = -0.55;
    for (const [x, z, s] of [[-7, -10, 1.3], [-10, -17, 1.6], [13, -9, 1.2], [-4, -23, 1.8], [4, -27, 1.5]]) {
      caixa(0.4 * s, 1.4 * s, 0.4 * s, "#6b4423", x, 0.7 * s, z, g); caixa(1.6 * s, 1.2 * s, 1.6 * s, "#2f9e44", x, 1.9 * s, z, g, true);
    }
    const sol = lowpoly(5, "#ffd27a", 2, 0.03, 4); sol.material = luz("#ffcf6a", 2.2); sol.position.set(-22, 9, -80); g.add(sol);
    g.add(particulas("#fff0b3", 180, 9, 0.05));
    return g;
  },
  oceano() {
    const g = grupo();
    g.userData.fundo = ceuGradiente("#2b6cb0", "#a7e0ff"); g.userData.neblina = ["#9fd3f0", 28, 110];
    luzes(g, { amb: "#cfe9ff", chao: "#1c5d8a", forca: 1.5, sol: "#fff4d6", solForca: 3.0, solPos: [8, 12, 6], contorno: "#ffffff" });
    const mar = new THREE.Mesh(new THREE.PlaneGeometry(300, 300), mat("#1e7fc2", { roughness: 0.25, metalness: 0.15 }));
    mar.rotation.x = -Math.PI / 2; mar.position.y = -0.35; mar.receiveShadow = true; g.add(mar);
    caixa(8, 0.6, 6, "#f2d49b", -0.3, -0.25, 0, g, true);
    caixa(0.35, 3.2, 0.35, "#8d6e63", -3.0, 1.6, -1.6, g).rotation.z = 0.12;
    for (let i = 0; i < 5; i++) { const f = caixa(2.2, 0.12, 0.6, "#2f9e44", -2.8, 3.2, -1.6, g, true); f.rotation.y = i * 1.25; f.rotation.z = -0.35; f.translateX(0.9); }
    const r = semente(9); g.userData.ondas = [];
    for (let i = 0; i < 40; i++) {
      const o = caixa(0.6 + r() * 1.2, 0.08, 0.2, "#e3f6ff", (r() - 0.5) * 50, -0.3, -4 - r() * 50, g); o.castShadow = false; g.userData.ondas.push([o, r() * 6]);
    }
    return g;
  },
  fundo_mar() {  // embaixo d'água: luz azul, raios de sol, algas e bolhas
    const g = grupo();
    g.userData.fundo = ceuGradiente("#0a3d62", "#062033"); g.userData.neblina = ["#0b4466", 6, 40]; g.userData.flutua = true;
    luzes(g, { amb: "#6fc3ff", chao: "#06263a", forca: 1.5, sol: "#a8e6ff", solForca: 2.6, solPos: [2, 14, 4], contorno: "#5cf2e3" });
    caixa(200, 0.2, 200, "#c2a878", 0, -0.1, -30, g);
    const r = semente(12);
    for (let i = 0; i < 40; i++) {
      const x = (r() - 0.5) * 30, z = -2 - r() * 25, h = 1 + r() * 3;
      for (let k = 0; k < h / 0.4; k++) caixa(0.22, 0.4, 0.22, r() > 0.5 ? "#2b8a3e" : "#37b24d", x + Math.sin(k) * 0.1, 0.2 + k * 0.4, z, g, true).castShadow = false;
    }
    for (let i = 0; i < 18; i++) caixa(0.6 + r(), 0.4 + r() * 0.5, 0.6 + r(), ["#ff6b6b", "#f783ac", "#ffa94d"][i % 3], (r() - 0.5) * 20, 0.2, -3 - r() * 18, g, true);
    for (let i = 0; i < 6; i++) {  // raios de luz vindo da superfície
      const raio = new THREE.Mesh(new THREE.BoxGeometry(0.8, 30, 0.1), new THREE.MeshBasicMaterial({ color: "#bfe9ff", transparent: true, opacity: 0.07, depthWrite: false, blending: THREE.AdditiveBlending }));
      raio.position.set(-8 + i * 3.2, 10, -10 - i); raio.rotation.z = 0.35; g.add(raio);
    }
    g.add(particulas("#d6f3ff", 220, 14, 0.07));
    return g;
  },
  supermercado() {
    const g = grupo();
    g.userData.fundo = ceuGradiente("#5d6876", "#7d8896"); g.userData.neblina = ["#727d8b", 18, 60];
    luzes(g, { amb: "#e6ecf5", chao: "#5d6670", forca: 0.9, sol: "#fff6e6", solForca: 1.4, solPos: [2, 12, 6], contorno: "#ffd59a" });
    caixa(60, 0.2, 60, "#8e99a6", 0, -0.1, -10, g);
    caixa(60, 12, 0.3, "#6f7a88", 0, 6, -32, g);
    for (let z = -6; z > -34; z -= 4) for (const x of [-5, 5]) {
      const p = construirModelo("prateleira", MODELOS.prateleira, semente(Math.abs(z * 7 + x)));
      p.position.set(x, 0, z); p.rotation.y = x < 0 ? Math.PI / 2 : -Math.PI / 2; g.add(p);
    }
    for (let z = -2; z > -30; z -= 5) caixa(3, 0.08, 0.6, luz("#fff3dc", 0.9), 0, 6, z, g);
    return g;
  },
};

// ---------- elenco: posição e movimento ----------

const LUGARES = { centro: [0, 0, 0], esquerda: [-1.25, 0, 0.4], direita: [1.25, 0, 0.4], fundo: [0, 0, -7], ceu: [0, 3.2, -2], chao: [0, 0, -1] };

function montarElenco(cena, i, extrasIA, temPersonagem) {
  const itens = [];
  (cena.elenco || []).forEach((item, k) => {
    const def = MODELOS[item.modelo] || (extrasIA || {})[item.modelo];
    if (!def) return;
    const qtd = Math.max(1, Math.min(item.qtd || 1, 60));
    const lugar = item.onde || (temPersonagem ? "direita" : "centro");
    const [cx, cy, cz] = LUGARES[lugar] || LUGARES.centro;
    const r = semente(1000 + i * 37 + k * 11);
    const espalha = item.acao === "espalhado";
    const raio = espalha ? 5 : 0.55 + Math.sqrt(qtd) * (def.tamanho || 1) * 0.45;
    for (let n = 0; n < qtd; n++) {
      const m = construirModelo(item.modelo, def, r, extrasIA);
      const escala = (item.escala || 1) * (qtd > 1 && !espalha ? 0.85 + r() * 0.3 : 1);
      const ang = r() * Math.PI * 2, dist = qtd === 1 ? 0 : Math.sqrt(r()) * raio;
      const voa = !m.userData.chao;
      const base = new THREE.Vector3(cx + Math.cos(ang) * dist * (espalha ? 1.6 : 1),
                                     cy + (voa ? 1.6 + (qtd > 1 ? (r() - 0.5) * raio * 0.8 : 0) : 0),
                                     cz + Math.sin(ang) * dist * (espalha ? 1.2 : 0.6));
      m.userData.inst = { base, escala, fase: r() * 6.28, atraso: qtd > 1 ? n / qtd : 0, rand: r() };
      m.visible = false; scene.add(m);
      itens.push({ m, acao: item.acao || "parado", qtd, k });
    }
  });
  return itens;
}

function animarItem({ m, acao }, tl, dur, t) {
  const { base, escala, fase, atraso, rand } = m.userData.inst, ud = m.userData;
  const entra = elastico((tl - atraso * Math.min(0.8, dur * 0.25)) / 0.55);
  let s = escala * Math.max(entra, 0.0001), x = base.x, y = base.y, z = base.z, ry = 0.5 + Math.sin(t * 0.6 + fase) * 0.2;
  if (!ud.chao) y += Math.sin(t * 1.8 + fase) * 0.08;
  if (acao === "gira") ry = t * 0.7;
  else if (acao === "enxame") {
    const v = 0.9 + rand * 0.8;
    x = base.x + Math.sin(t * v + fase) * 1.1; y = base.y + Math.sin(t * v * 1.7 + fase * 2) * 0.45; z = base.z + Math.cos(t * v + fase) * 0.7;
    ry = Math.atan2(Math.cos(t * v + fase), -Math.sin(t * v + fase));
  } else if (acao === "voa") {
    x = lerp(-7, 7, ((tl / Math.max(dur, 1)) * (0.8 + rand * 0.5) + atraso) % 1); ry = Math.PI / 2;
  } else if (acao === "anda") {
    x = lerp(-6, 6, ((tl / Math.max(dur, 1)) * 0.6 + atraso) % 1) + base.x * 0.2; ry = Math.PI / 2; y += Math.abs(Math.sin(t * 8 + fase)) * 0.08;
  } else if (acao === "cai") {
    const t0 = tl - atraso * 0.8, k = clamp01(t0 / 0.9);
    const quique = k < 1 ? 0 : Math.abs(Math.sin((t0 - 0.9) * 9)) * Math.exp(-(t0 - 0.9) * 4) * 0.4;
    y = lerp(base.y + 8, base.y, k * k) + quique; s = escala; ry = fase;
  } else if (acao === "cresce") s = escala * Math.max(elastico((tl - atraso * 0.5) / Math.max(dur * 0.6, 0.6)), 0.0001);
  else if (acao === "some") {
    const ini = dur * 0.25 + atraso * dur * 0.5;
    s = escala * Math.max(entra, 0.0001) * (1 - suave((tl - ini) / 0.35));
    y += suave((tl - ini) / 0.35) * 0.6;
  } else if (acao === "orbita") {
    const a = t * 0.8 + fase; x = Math.cos(a) * 2.2; z = Math.sin(a) * 1.2 + base.z; ry = -a;
  } else if (acao === "pula") y += Math.abs(Math.sin(t * 6 + fase)) * 0.45;
  else if (acao === "pulsa") s *= 1 + Math.abs(Math.sin(t * 5)) * 0.12;
  else if (acao === "treme") { x += Math.sin(t * 50 + fase) * 0.04; y += Math.cos(t * 43 + fase) * 0.03; }
  m.position.set(x, y, z); m.rotation.set(0, ry, 0); m.scale.setScalar(s);
  for (const a of ud.partes.asas) a.rotation.z = Math.sin(t * 38 + fase) * 0.7 * a.userData.lado;
  for (const c of ud.partes.chamas) c.scale.set(1, 0.8 + Math.abs(Math.sin(t * 22 + fase)) * 0.45, 1);
  if (ud.partes.ponteiro) ud.partes.ponteiro.rotation.z = -t * 3;
}

// ---------- câmera de cinema ----------

function enquadrar(cena, tl, dur, t) {
  const F = cena.foco.clone(), S = cena.tamanhoFoco;
  const d = Math.max(3.6, Math.min(S * 2.3, 34));
  const k = suave2(tl / Math.max(dur, 0.1));
  let de, para;
  const olhar = F.clone();
  switch (cena.camera) {
    case "afasta": de = new THREE.Vector3(0, 0.2, d * 0.65); para = new THREE.Vector3(0, 1.4, d * 1.7); break;
    case "orbita": {
      const a = lerp(-0.6, 0.6, k);
      de = para = new THREE.Vector3(Math.sin(a) * d * 1.15, 0.7, Math.cos(a) * d * 1.15); break;
    }
    case "grua": de = new THREE.Vector3(0, -Math.min(F.y - 0.3, 0.8), d * 1.05); para = new THREE.Vector3(0, 2.8, d * 1.25); break;
    case "close": de = new THREE.Vector3(0.1, 0.12, d * 1.0); para = new THREE.Vector3(0, 0.08, d * 0.85); break;
    case "geral": de = new THREE.Vector3(0, 4.8, d * 3.0); para = new THREE.Vector3(0, 3.9, d * 2.5); olhar.y += 0.4; break;
    case "lateral": de = new THREE.Vector3(-d * 0.45, 0.4, d); para = new THREE.Vector3(d * 0.45, 0.4, d); break;
    case "baixo": de = new THREE.Vector3(0.2, -F.y + 0.45, d * 0.95); para = new THREE.Vector3(0.1, -F.y + 0.55, d * 0.8); olhar.y += 0.5; break;
    default: de = new THREE.Vector3(0.35, 0.55, d * 1.35); para = new THREE.Vector3(0.1, 0.3, d);  // aproxima
  }
  const pos = F.clone().add(de.clone().lerp(para, k));
  pos.y = Math.max(pos.y, 0.35);
  pos.x += Math.sin(t * 0.9) * 0.04; pos.y += Math.sin(t * 1.3) * 0.03;  // câmera na mão
  camera.position.copy(pos); camera.lookAt(olhar);
  foco.uniforms.focus.value = pos.distanceTo(F);
}

// ---------- HUD ----------

const $ = (id) => document.getElementById(id);
const faixa = $("faixa"), contador = $("contador"), legenda = $("legenda"), corte = $("corte");

function formatarNumero(n, casas) {
  return n.toLocaleString(SB.lang === "en" ? "en-US" : "pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}
function blocosLegenda(palavras) {
  const blocos = []; let atual = [];
  for (const p of palavras) { atual.push(p); if (atual.length === 3 || /[.,!?;:]$/.test(p.palavra)) { blocos.push(atual); atual = []; } }
  if (atual.length) blocos.push(atual);
  return blocos;
}
function desenharHud(t, cena, tl) {
  if (cena.texto_topo) {
    faixa.style.display = "block";
    const txt = (cena.texto_topo.texto || "").toUpperCase(), d = (cena.texto_topo.destaque || "").toUpperCase();
    const html = d && txt.includes(d) ? txt.replace(d, `<span class="d">${d}</span>`) : txt;
    if (faixa.dataset.html !== html) { faixa.innerHTML = html; faixa.dataset.html = html; }
    faixa.style.transform = `translateX(-50%) rotate(-1.2deg) scale(${0.6 + 0.4 * elastico(tl / 0.5)})`;
    faixa.style.opacity = clamp01(tl / 0.15);
  } else faixa.style.display = "none";
  if (cena.contador) {
    const c = cena.contador; contador.style.display = "block";
    const valor = lerp(c.de ?? 0, c.ate, suave(tl / Math.max((cena.fim - cena.inicio) * 0.7, 0.3)));
    contador.querySelector(".n").textContent = (c.prefixo || "") + formatarNumero(valor, c.casas || 0) + (c.sufixo || "");
    contador.querySelector(".r").textContent = c.rotulo || "";
    contador.style.transform = `translateX(-50%) scale(${0.5 + 0.5 * elastico(tl / 0.5)})`;
  } else contador.style.display = "none";
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

let SB = null, BLOCOS = [], CENAS = [], EXP = null;

window.preparar = async (storyboard) => {
  SB = storyboard;
  tamanhoRender(SB.escala_3d || 1);
  await document.fonts.load('88px "Archivo"');
  BLOCOS = blocosLegenda(SB.palavras || []);
  const extrasIA = SB.modelos_novos || {};
  const cenarios = {};
  for (const nome of new Set(SB.cenas.map((c) => c.cenario))) {
    const g = (CENARIOS[nome] || CENARIOS.estudio)(); g.visible = false; scene.add(g); cenarios[nome] = g;
  }
  EXP = criarExplorador(); scene.add(EXP.raiz);
  CENAS = SB.cenas.map((c, i) => {
    const pers = c.personagem && typeof c.personagem === "object" ? c.personagem : (c.personagem ? { acao: c.acao || "fala" } : null);
    const itens = montarElenco(c, i, extrasIA, !!pers);
    // foco da câmera: o assunto (média do elenco) ou o rosto do explorador
    const fc = new THREE.Vector3();
    let tam = 1.6;
    const lugarP = pers ? (LUGARES[pers.onde] || (itens.length ? LUGARES.esquerda : LUGARES.centro)) : null;
    if (itens.length && c.foco !== "personagem") {
      // o primeiro item do elenco é o assunto principal; o resto é ambiente
      const principais = itens.filter((it) => it.k === 0);
      const caixaA = new THREE.Box3();
      for (const it of principais) {
        const { base, escala } = it.m.userData.inst;
        it.m.position.copy(base); it.m.scale.setScalar(escala); it.m.updateMatrixWorld(true);
        caixaA.expandByObject(it.m);
      }
      const esfera = caixaA.getBoundingSphere(new THREE.Sphere());
      const mov = { enxame: 1.2, orbita: 2.3, voa: 3.5, anda: 3.5, cai: 0.3, pula: 0.4 }[principais[0].acao] || 0;
      fc.copy(esfera.center);
      if (["voa", "anda"].includes(principais[0].acao)) fc.x = 0;
      // muito espalhado (cenário inteiro): foca no pedaço mais perto da câmera
      tam = Math.min(esfera.radius + mov, 6) * 2;
      if (pers) { fc.x = (fc.x + lugarP[0]) / 2; fc.y = Math.max(fc.y, 1.9); tam = Math.max(tam, 4.0); }
    } else if (pers) {
      fc.set(lugarP[0], 2.45, lugarP[2]); tam = 1.9;
    } else fc.set(0, 1.5, 0);
    return { ...c, n: i, grupo: cenarios[c.cenario] || Object.values(cenarios)[0], itens, pers, lugarP, foco: fc, tamanhoFoco: tam };
  });
  return SB.duracao;
};

window.quadro = (t) => {
  let cena = CENAS[CENAS.length - 1];
  for (const c of CENAS) if (t >= c.inicio && t < c.fim) { cena = c; break; }
  const tl = t - cena.inicio, dur = cena.fim - cena.inicio;

  for (const c of CENAS) { c.grupo.visible = false; for (const it of c.itens) it.m.visible = false; }
  const g = cena.grupo; g.visible = true;
  scene.background = g.userData.fundo;
  scene.fog = g.userData.neblina ? new THREE.Fog(...g.userData.neblina) : null;
  grade.uniforms.quente.value = g.userData.quente || 0;
  if (g.userData.planeta) g.userData.planeta.rotation.y = t * 0.03;
  for (const [o, fase] of g.userData.ondas || []) o.position.y = -0.3 + Math.sin(t * 1.6 + fase) * 0.06;
  g.traverse((o) => o.userData.animar && o.userData.animar(t));

  for (const it of cena.itens) { it.m.visible = true; animarItem(it, tl, dur, t); }

  EXP.raiz.visible = !!cena.pers;
  if (cena.pers) {
    const falando = (SB.palavras || []).some((p) => t >= p.inicio && t < p.fim);
    const flut = g.userData.flutua;
    EXP.raiz.position.set(cena.lugarP[0], flut ? 0.9 + Math.sin(t * 1.2) * 0.15 : 0, cena.lugarP[2]);
    EXP.raiz.rotation.set(flut ? Math.sin(t * 0.7) * 0.08 : 0, cena.itens.length ? 0.35 : 0.12, flut ? Math.sin(t * 0.9) * 0.06 : 0);
    if (cena.pers.acao === "anda") EXP.raiz.position.x = lerp(cena.lugarP[0] - 2.2, cena.lugarP[0], suave(tl / Math.min(dur, 1.6)));
    posarExplorador(EXP, cena.pers.acao || "fala", tl, t, falando);
  }

  enquadrar(cena, tl, dur, t);
  corte.style.opacity = cena.n > 0 && tl < 0.1 ? 1 - tl / 0.1 : 0;  // corte seco com 3 quadros de escuro
  grade.uniforms.tempo.value = (t * 30) % 97;
  desenharHud(t, cena, tl);
  composer.render();
};

window.pronto = true;
