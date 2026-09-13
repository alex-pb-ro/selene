# Vendored browser assets

These upstream distributions are served locally. URLs record provenance; the application does not fetch them at runtime. Adjacent license files preserve the projects’ terms.

| File | Version and source | SHA-256 |
| --- | --- | --- |
| [src/selene/resources/dashboard/vendor/chart.umd.min.js](../src/selene/resources/dashboard/vendor/chart.umd.min.js) | [Chart.js 4.5.1](https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js) | `48444a82d4edcb5bec0f1965faacdde18d9c17db3063d042abada2f705c9f54a` |
| [src/selene/resources/dashboard/vendor/chartjs-plugin-datalabels.min.js](../src/selene/resources/dashboard/vendor/chartjs-plugin-datalabels.min.js) | [chartjs-plugin-datalabels 2.2.0](https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js) | `20c08f3d9c6d2ef76df6d6a6f1127c0013339fe32add24222276c398c6308c38` |
| [docs/_static/vendor/tex-svg-full.js](../docs/_static/vendor/tex-svg-full.js) | [MathJax 3.2.2](https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg-full.js) | `a4354ff94fd868aea0cc6eaaa79a57fda0588646fc46ee3700a349ee0a11cbe6` |

The existing jQuery 3.7.1 distribution retains its embedded OpenJS/MIT notice. Browser assets are ordinary third-party code; vendoring fixes the reviewed bytes and removes automatic CDN traffic, but is not a proof of their correctness.
