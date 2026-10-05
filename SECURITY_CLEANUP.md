# API 凭据清理说明

## 清理结果

本包基于用户上传的 `LLMNego_Plus.rar` 制作，仅修改本地副本，未访问或修改远程 GitHub 仓库。

发现并移除 **6 个不同的硬编码 API 凭据值，共 74 处出现**，涉及 **70 个 Notebook 和 2 个 Python 配置文件**。
这包含可执行代码中的凭据、注释中的旧凭据，以及配置文件中的硬编码回退值。
未使用这些凭据请求任何服务，未判断它们是否仍然有效。本文不记录原始密钥、片段或密钥哈希。

| 服务 | 不同凭据值数量 | 原始出现次数 | 修改后的环境变量 |
| --- | ---: | ---: | --- |
| OpenAI | 2 | 5 | `OPENAI_API_KEY` |
| DeepSeek | 2 | 66 | Notebook 使用 `DEEPSEEK_API_KEY`；修复的两个配置文件优先使用 `NEGO_API_KEY`，未设置时读取 `DEEPSEEK_API_KEY` |
| Google Gemini | 1 | 2 | `GEMINI_API_KEY` |
| Qwen / DashScope | 1 | 1 | `DASHSCOPE_API_KEY` |

## 具体修改

1. 将 Notebook 中的明文凭据改为 `os.environ["对应环境变量"]`，并在需要的单元格补充 `import os`。
2. 移除一个 Notebook 中向 `os.environ["OPENAI_API_KEY"]` 写入硬编码密钥的语句；不覆盖用户事先设置的环境变量。
3. 清理包含旧凭据的注释，将提示用户直接替换源代码密钥的相关注释改为环境变量说明。
4. 修复 `EXP/0423_strategic_buyer/config.py` 和 `EXP/0425_strategic_buyer_2/config.py`：不再在环境变量缺失时回退到泄露密钥；优先读取 `NEGO_API_KEY`，未设置时读取 `DEEPSEEK_API_KEY`，两者均未设置时使用空字符串。
5. 增加不含任何密钥的 `.env.example`，更新 README 的配置说明，并在 `.gitignore` 中增加本地环境文件、常见凭据文件及 Notebook 检查点的忽略规则。

## 保留范围

原始压缩包中的 **5,165 个文件全部保留**。其中 72 个含凭据的文件、README 和 `.gitignore` 被有意修改，其余 **5,091 个文件**均通过与原始 RAR 文件记录的大小及 CRC32 比较，确认没有内容变化。

所有原有 Notebook 的实验输出、单元格元数据，以及原有实验 JSON、日志、图片和其他数据均予以保留。70 个被修改的 Notebook 已逐个检查，输出和单元格元数据与原件一致。此次未发现必须删除的含密钥输出单元格。

两个嵌套的 `merged_results.rar` 内容完全相同（已比较整个压缩文件的 SHA-256）。已将其中一份实际解压，检查其全部 120 个 JSON 文件，未发现所检查模式的凭据，因此两份嵌套压缩包均原样保留。它们不是因为“压缩状态下没有命中”而被跳过。

## 验证

- 对完整目录及解压后的嵌套数据进行凭据格式扫描，并检查认证头、JWT、私钥、URL 内嵌认证信息和常见的凭据赋值形式；无待处理的真实凭据匹配。
- 对全部 6 个已发现的原始凭据及其常见文本编码形式进行精确复扫，未发现残留。
- 149 个 Python 文件通过语法编译检查。
- 132 个 Notebook 成功解析，其中 678 个代码单元格通过适用于 IPython 语法的静态编译检查。
- 针对修改后的凭据读取表达式完成 148 项本地断言，覆盖读取环境变量、缺失变量，以及两个配置文件的优先级和空值回退行为。
- 额外检查 Notebook JSON 解码后的文本、197 个内嵌 PNG 输出的数据及元数据、37 个独立 PNG 文件的元数据，以及 1 个十页 PDF 的可提取文本与解压对象流；未发现上述凭据残留。

这些检查没有执行谈判实验、调用模型 API、验证密钥状态或产生模型调用费用。语法检查不等于所有实验均已端到端运行成功。

## 使用方式

在启动 Python / Jupyter 的终端中设置对应服务的环境变量。现有其他实验脚本通常仍使用 `NEGO_API_KEY`，所以运行 DeepSeek 实验时建议同时在本地设置 `DEEPSEEK_API_KEY` 与 `NEGO_API_KEY`。

`.env.example` 只是变量名模板，不包含可用密钥。本项目不会自动加载 `.env` 文件；需要显式设置进程环境变量，或由你在本地使用环境变量加载器。已经启动的 Jupyter 进程不会自动继承后来在另一个终端中设置的变量。

未修改的不含真实凭据的历史模板中仍可能存在 `YOUR_*` 占位符；使用这些模板时，请将占位符改为环境变量读取，而不是把新密钥写回文件。

## 安全边界与尚需用户处理的事项

此次清理仅针对所上传压缩包的内容。原始上传包、其他本地副本、GitHub 上的文件、提交历史、缓存或已经下载出去的副本不会因此被改变。原包不包含 `.git` 目录，因此没有可在本包中清理的 Git 提交历史。

删除源代码中的密钥并不等于撤销密钥。已暴露的凭据需要由账户所有者到相应服务控制台撤销或轮换，随后把新值配置到本地环境变量中。`.gitignore` 也不会自动取消对既有已跟踪文件的跟踪。

复扫结果针对已识别凭据及所检查的模式，不是对任何未知密钥或任意编码形式的绝对保证。未对所有图片像素执行 OCR，未验证外部账户权限，也未审计完整程序的其他安全问题。

## 含凭据文件的逐项修改清单

下面只列文件路径、移除次数和环境变量，不包含任何原始凭据。

| 文件 | 移除次数 | 使用的环境变量 |
| --- | ---: | --- |
| `EXP/0321_first_demo/first_demo_deepseek.ipynb` | 2 | `DEEPSEEK_API_KEY` |
| `EXP/0321_first_demo/first_demo_gpt.ipynb` | 1 | `OPENAI_API_KEY` |
| `EXP/0321_first_demo/first_demo_qwen.ipynb` | 1 | `DASHSCOPE_API_KEY` |
| `EXP/0322/first_demo_gpt_4o.ipynb` | 1 | `OPENAI_API_KEY` |
| `EXP/0324_hacking_direct/simple_attack.ipynb` | 1 | `OPENAI_API_KEY` |
| `EXP/0326_hacking_w_phrasing/simple_attack_w_embedding.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0403_hacking_methods/A1_w_persona_attack.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0403_hacking_methods/A2_w_naive_injection.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0403_hacking_methods/A3_w_ContextIgnore.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0403_hacking_methods/A4_w_ComboInjection.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0403_hacking_methods/A5_w_FakeComplete.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0403_hacking_methods/A6_w_EscapeChar.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0403_hacking_methods/A7_w_Obfuscation.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0403_hacking_methods/A8_w_TransferSuffix.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A10_w_PAIRIterativeRefinement.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A11_w_DeepInception.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A12_w_MHJTactics.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A13_w_ChatHistoryTampering.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A14_w_NEXUS.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A15_w_AttentionShifting.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A16_w_PromptfooMultiTurn.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A17_w_PANDASManyShot.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A18_w_HaPLaLaundering.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A19_w_ArtPerceptionASCII.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A20_w_ArtPromptASCII.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A21_w_SyntheticRecollections.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A22_w_BoundaryPointBinaryFeedback.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A23_w_DataFlipKAD.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A24_w_VerdictTargeting.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A25_w_PISmith.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A26_w_RLHammer.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0404_hacking_methods/A9_w_AutoPersonaModulation.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0411_model_assump_check/A1_10EXPS_20Rounds.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0411_model_assump_check/A2_coke_Buyer_MultipleStrategy_20rounds.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0411_model_assump_check/A3_w_Gemini_2.5_flash.ipynb` | 1 | `GEMINI_API_KEY` |
| `EXP/0411_model_assump_check/A4_w_Gemini_2.5_pro.ipynb` | 1 | `GEMINI_API_KEY` |
| `EXP/0411_model_assump_check/A5_w_GPT_4o.ipynb` | 2 | `OPENAI_API_KEY` |
| `EXP/0412_ablations/Sweep_B.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0413_final_validation_of_function_type/run_all_1.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0413_final_validation_of_function_type/run_all_1_budget.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0413_final_validation_of_function_type/run_all_2.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0413_final_validation_of_function_type/run_all_2_budget.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0413_final_validation_of_function_type/run_all_3.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0413_final_validation_of_function_type/run_all_3_budget.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0413_final_validation_of_function_type/run_all_4.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0413_final_validation_of_function_type/run_all_4_budget.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb1.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb10.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb11.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb12.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb2.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb3.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb4.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb5.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb6.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb7.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb8.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0416_new_dataset_creation/run_all_0416b_nb9.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb1.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb10.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb11.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb12.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb2.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb3.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb4.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb5.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb6.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb7.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb8.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0418_more_finegrained_dataset/run_all_0418_nb9.ipynb` | 1 | `DEEPSEEK_API_KEY` |
| `EXP/0423_strategic_buyer/config.py` | 1 | `NEGO_API_KEY` / `DEEPSEEK_API_KEY` |
| `EXP/0425_strategic_buyer_2/config.py` | 1 | `NEGO_API_KEY` / `DEEPSEEK_API_KEY` |
