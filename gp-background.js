/**
 * Animated GP Posterior Background — Full Page.
 *
 * Renders a Gaussian process posterior (mean, variance band, samples)
 * behind all page content. Samples rotate along equi-probability
 * ellipses of the posterior as the user scrolls.
 */
(function () {
    'use strict';

    // ─── Configuration ───────────────────────────────────────────────────
    const NUM_SAMPLES = 4;
    const GRID_SIZE = 100;
    const NOISE_VAR = 0.04;
    const KERNEL_VAR = 1.0;
    const LENGTH_SCALE = 0.18;
    const OPACITY_MEAN = 0.15;
    const OPACITY_BAND = 0.06;
    const OPACITY_SAMPLE = 0.10;
    const SCROLL_SPEED = 0.0008;
    const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // ─── Fake observed data ──────────────────────────────────────────────
    const xObs = [0.08, 0.22, 0.35, 0.52, 0.68, 0.82, 0.93];
    const yObs = [0.3, -0.5, 0.2, 0.8, -0.1, 0.6, -0.3];

    // ─── Canvas setup ────────────────────────────────────────────────────
    const canvas = document.createElement('canvas');
    canvas.id = 'gp-background';
    canvas.setAttribute('aria-hidden', 'true');
    document.body.prepend(canvas);
    const ctx = canvas.getContext('2d');

    let W, H, dpr;
    let scrollY = 0;
    let ticking = false;

    // ─── Precomputed posterior data ──────────────────────────────────────
    let xGrid = [];
    let mean = [];
    let stddev = [];
    let sampleBases = []; // [{La, Lb, phaseOffset}] — pre-multiplied by Cholesky
    let accentColor = '';  // cached, updated on theme change

    // ─── Linear algebra helpers ──────────────────────────────────────────
    function rbfKernel(x1, x2) {
        const d = x1 - x2;
        return KERNEL_VAR * Math.exp(-0.5 * d * d / (LENGTH_SCALE * LENGTH_SCALE));
    }

    function buildKernelMatrix(xs1, xs2) {
        const n1 = xs1.length, n2 = xs2.length;
        const K = new Array(n1);
        for (let i = 0; i < n1; i++) {
            K[i] = new Float64Array(n2);
            for (let j = 0; j < n2; j++) {
                K[i][j] = rbfKernel(xs1[i], xs2[j]);
            }
        }
        return K;
    }

    function cholesky(A, n) {
        const L = new Array(n);
        for (let i = 0; i < n; i++) L[i] = new Float64Array(n);
        for (let i = 0; i < n; i++) {
            for (let j = 0; j <= i; j++) {
                let sum = A[i][j];
                for (let k = 0; k < j; k++) sum -= L[i][k] * L[j][k];
                if (i === j) {
                    L[i][j] = Math.sqrt(Math.max(sum, 1e-10));
                } else {
                    L[i][j] = sum / L[j][j];
                }
            }
        }
        return L;
    }

    function forwardSolve(L, b, n) {
        const x = new Float64Array(n);
        for (let i = 0; i < n; i++) {
            let sum = b[i];
            for (let k = 0; k < i; k++) sum -= L[i][k] * x[k];
            x[i] = sum / L[i][i];
        }
        return x;
    }

    function backwardSolve(L, b, n) {
        const x = new Float64Array(n);
        for (let i = n - 1; i >= 0; i--) {
            let sum = b[i];
            for (let k = i + 1; k < n; k++) sum -= L[k][i] * x[k];
            x[i] = sum / L[i][i];
        }
        return x;
    }

    function matvec(M, v, nRows, nCols) {
        const result = new Float64Array(nRows);
        for (let i = 0; i < nRows; i++) {
            let sum = 0;
            for (let j = 0; j < nCols; j++) sum += M[i][j] * v[j];
            result[i] = sum;
        }
        return result;
    }

    function gaussianRandom() {
        let u1 = Math.random();
        if (u1 === 0) u1 = 1e-10;
        const u2 = Math.random();
        return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    }

    // ─── Compute GP posterior ────────────────────────────────────────────
    function computePosterior() {
        const nObs = xObs.length;
        const nGrid = GRID_SIZE;

        xGrid = new Float64Array(nGrid);
        for (let i = 0; i < nGrid; i++) xGrid[i] = i / (nGrid - 1);

        const Kxx = buildKernelMatrix(xObs, xObs);
        for (let i = 0; i < nObs; i++) Kxx[i][i] += NOISE_VAR;

        const Lxx = cholesky(Kxx, nObs);
        const Ksx = buildKernelMatrix(xGrid, xObs);

        const alpha1 = forwardSolve(Lxx, yObs, nObs);
        const alpha = backwardSolve(Lxx, alpha1, nObs);

        mean = matvec(Ksx, alpha, nGrid, nObs);

        const V = new Array(nObs);
        for (let i = 0; i < nObs; i++) V[i] = new Float64Array(nGrid);
        for (let j = 0; j < nGrid; j++) {
            const col = new Float64Array(nObs);
            for (let i = 0; i < nObs; i++) col[i] = Ksx[j][i];
            const v = forwardSolve(Lxx, col, nObs);
            for (let i = 0; i < nObs; i++) V[i][j] = v[i];
        }

        const Kss = buildKernelMatrix(xGrid, xGrid);
        const posteriorCov = new Array(nGrid);
        for (let i = 0; i < nGrid; i++) {
            posteriorCov[i] = new Float64Array(nGrid);
            for (let j = 0; j < nGrid; j++) {
                let vTv = 0;
                for (let k = 0; k < nObs; k++) vTv += V[k][i] * V[k][j];
                posteriorCov[i][j] = Kss[i][j] - vTv;
            }
        }

        stddev = new Float64Array(nGrid);
        for (let i = 0; i < nGrid; i++) {
            stddev[i] = Math.sqrt(Math.max(posteriorCov[i][i], 0));
        }

        for (let i = 0; i < nGrid; i++) posteriorCov[i][i] += 1e-8;
        const cholL = cholesky(posteriorCov, nGrid);

        // Pre-compute L*a and L*b for each sample (avoids O(n²) per frame)
        sampleBases = [];
        for (let s = 0; s < NUM_SAMPLES; s++) {
            const a = new Float64Array(nGrid);
            let normA = 0;
            for (let i = 0; i < nGrid; i++) {
                a[i] = gaussianRandom();
                normA += a[i] * a[i];
            }
            normA = Math.sqrt(normA);

            const b = new Float64Array(nGrid);
            let dot = 0;
            for (let i = 0; i < nGrid; i++) {
                b[i] = gaussianRandom();
                dot += b[i] * a[i];
            }
            const scale = dot / (normA * normA);
            let normB = 0;
            for (let i = 0; i < nGrid; i++) {
                b[i] -= scale * a[i];
                normB += b[i] * b[i];
            }
            normB = Math.sqrt(normB);

            const targetNorm = Math.sqrt(nGrid) * (0.5 + Math.random() * 0.3);
            for (let i = 0; i < nGrid; i++) {
                a[i] = (a[i] / normA) * targetNorm;
                b[i] = (b[i] / normB) * targetNorm;
            }

            // Pre-multiply: La = L*a, Lb = L*b (O(n²) once at init)
            const La = new Float64Array(nGrid);
            const Lb = new Float64Array(nGrid);
            for (let i = 0; i < nGrid; i++) {
                let sumA = 0, sumB = 0;
                for (let j = 0; j <= i; j++) {
                    sumA += cholL[i][j] * a[j];
                    sumB += cholL[i][j] * b[j];
                }
                La[i] = sumA;
                Lb[i] = sumB;
            }

            sampleBases.push({ La, Lb, phaseOffset: Math.random() * Math.PI * 2 });
        }
    }

    // ─── Compute a sample at angle θ (O(n) — just linear combination) ───
    function computeSample(sampleIdx, theta) {
        const { La, Lb, phaseOffset } = sampleBases[sampleIdx];
        const angle = theta + phaseOffset;
        const cosA = Math.cos(angle);
        const sinA = Math.sin(angle);
        const nGrid = GRID_SIZE;

        // f(θ) = μ + cos(θ)·(L*a) + sin(θ)·(L*b)
        const sample = new Float64Array(nGrid);
        for (let i = 0; i < nGrid; i++) {
            sample[i] = mean[i] + cosA * La[i] + sinA * Lb[i];
        }
        return sample;
    }

    // ─── Drawing ─────────────────────────────────────────────────────────
    function toScreenX(x) { return x * W; }
    function toScreenY(y) {
        return H * 0.5 - y * H * 0.22;
    }

    function drawSmoothCurve(ys) {
        const n = ys.length;
        ctx.moveTo(toScreenX(xGrid[0]), toScreenY(ys[0]));
        for (let i = 1; i < n - 1; i++) {
            const x0 = toScreenX(xGrid[i]);
            const y0 = toScreenY(ys[i]);
            const x1 = toScreenX(xGrid[i + 1]);
            const y1 = toScreenY(ys[i + 1]);
            ctx.quadraticCurveTo(x0, y0, (x0 + x1) / 2, (y0 + y1) / 2);
        }
        ctx.lineTo(toScreenX(xGrid[n - 1]), toScreenY(ys[n - 1]));
    }

    function draw() {
        ctx.clearRect(0, 0, W, H);

        const accent = accentColor;
        const theta = REDUCED_MOTION ? 0 : scrollY * SCROLL_SPEED;

        // ── Variance band (±2σ) ──────────────────────────────────────────
        ctx.beginPath();
        ctx.globalAlpha = OPACITY_BAND;
        ctx.fillStyle = accent;

        const n = GRID_SIZE;
        ctx.moveTo(toScreenX(xGrid[0]), toScreenY(mean[0] + 2 * stddev[0]));
        for (let i = 1; i < n - 1; i++) {
            const x0 = toScreenX(xGrid[i]);
            const y0 = toScreenY(mean[i] + 2 * stddev[i]);
            const x1 = toScreenX(xGrid[i + 1]);
            const y1 = toScreenY(mean[i + 1] + 2 * stddev[i + 1]);
            ctx.quadraticCurveTo(x0, y0, (x0 + x1) / 2, (y0 + y1) / 2);
        }
        ctx.lineTo(toScreenX(xGrid[n - 1]), toScreenY(mean[n - 1] + 2 * stddev[n - 1]));

        ctx.lineTo(toScreenX(xGrid[n - 1]), toScreenY(mean[n - 1] - 2 * stddev[n - 1]));
        for (let i = n - 2; i > 0; i--) {
            const x0 = toScreenX(xGrid[i]);
            const y0 = toScreenY(mean[i] - 2 * stddev[i]);
            const x1 = toScreenX(xGrid[i - 1]);
            const y1 = toScreenY(mean[i - 1] - 2 * stddev[i - 1]);
            ctx.quadraticCurveTo(x0, y0, (x0 + x1) / 2, (y0 + y1) / 2);
        }
        ctx.lineTo(toScreenX(xGrid[0]), toScreenY(mean[0] - 2 * stddev[0]));
        ctx.closePath();
        ctx.fill();

        // ── Posterior samples ────────────────────────────────────────────
        for (let s = 0; s < NUM_SAMPLES; s++) {
            const sample = computeSample(s, theta);
            ctx.beginPath();
            ctx.globalAlpha = OPACITY_SAMPLE;
            ctx.strokeStyle = accent;
            ctx.lineWidth = 1.5;
            drawSmoothCurve(sample);
            ctx.stroke();
        }

        // ── Posterior mean ───────────────────────────────────────────────
        ctx.beginPath();
        ctx.globalAlpha = OPACITY_MEAN;
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2;
        drawSmoothCurve(mean);
        ctx.stroke();

        ctx.globalAlpha = 1;
    }

    // ─── Resize ──────────────────────────────────────────────────────────
    function resize() {
        dpr = window.devicePixelRatio || 1;
        W = window.innerWidth;
        H = window.innerHeight;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        draw();
    }

    // ─── Scroll handler ──────────────────────────────────────────────────
    function onScroll() {
        scrollY = window.scrollY;
        if (!ticking && !REDUCED_MOTION) {
            ticking = true;
            requestAnimationFrame(() => {
                draw();
                ticking = false;
            });
        }
    }

    // ─── Theme change ────────────────────────────────────────────────────
    function updateAccentColor() {
        accentColor = getComputedStyle(document.documentElement)
            .getPropertyValue('--accent-color').trim() || '#0a7ea8';
    }
    const themeObserver = new MutationObserver(() => {
        updateAccentColor();
        requestAnimationFrame(draw);
    });
    themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme']
    });

    // ─── Init ────────────────────────────────────────────────────────────
    computePosterior();
    updateAccentColor();
    window.addEventListener('resize', resize, { passive: true });
    window.addEventListener('scroll', onScroll, { passive: true });
    resize();
})();
