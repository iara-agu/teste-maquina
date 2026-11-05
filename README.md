# teste-maquina

Confere se uma máquina Windows consegue rodar a Iara. Baixe o `teste-iara.exe`
da [última release](../../releases/latest) **pelo navegador**, rode e aguarde
de 1 a 3 minutos.

O que ele verifica:

- se um executável sem assinatura roda a partir de Downloads e de `%LOCALAPPDATA%`;
- se o cofre do Windows (DPAPI) grava e lê;
- quais `git`/`python` existem e o que a política do PowerShell permite;
- se GitHub, Anthropic, Claude e Super Sapiens respondem (só confere se o endereço responde);
- se uma página local em `127.0.0.1` abre no navegador.

Não pede nem guarda senha e não envia nada a lugar nenhum. Grava só
`relatorio-teste-iara.txt` (ao lado do executável ou na pasta temporária).

Código: [`teste_iara.py`](teste_iara.py), só biblioteca padrão do Python,
empacotado com `pyinstaller --onefile --console --name teste-iara --noupx teste_iara.py`.
