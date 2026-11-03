# Third-party software and research

AGH's implementation is independently written. No vendor cache, original article PDF or substantial code block from the comparison repositories is included.

- Zheng Zhenlong, Zhu Tiansheng, Chen Rong (2025), 中国可转债定价模型比较研究, China Economic Quarterly 25(1),173–190, DOI10.13821/j.cnki.ceq.2025.01.11. Published target numbers are transcribed as factual comparison targets with page provenance, not claimed as computed output. [Article](https://nsd.pku.edu.cn/docs/20250227142007660959.pdf), [appendix](https://nsd.pku.edu.cn/docs/20250227142513335689.pdf).
- [QuantLib official convertible example](https://github.com/lballabio/QuantLib/blob/master/Examples/ConvertibleBonds/ConvertibleBonds.cpp): reviewed as an engineering comparator. [QuantLib license](https://www.quantlib.org/license.shtml) is modified three-clause BSD. The example's binomial engines and hypothetical contracts do not supply Chinese rolling clause history or the paper's dataset.
- [Convertible-Bond-Pricing-Research](https://github.com/ericxuzhesheng/Convertible-Bond-Pricing-Research): reviewed as a separate implementation, MIT licensed. Its weekly2019+BS/ZL/LSM research and provider caches are not the original monthly2000–2022five-model panel. No data or source files were copied. Do not infer vendor redistribution rights from its software license.
- Direct dependencies include NumPy, SciPy, pandas, statsmodels, FastAPI, Starlette, uvicorn, httpx, Pydantic, Jinja2 and pypdf. Their distributions retain their own licenses and notices. Re-distributors must review the exact locked distributions rather than assume AGH's MIT license covers all dependencies.
- Tushare, arXiv, GitHub and Hugging Face content remains subject to the relevant provider and artifact licenses. Default packages contain metadata, summaries and manifests, not a grant to relicense external observations or model weights.

Audit date:2026-11-03. Reference comparisons establish design context, not production or performance acceptance.
