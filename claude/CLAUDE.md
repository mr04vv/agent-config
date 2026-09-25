@~/.codex/AGENTS.md

## Claude Code 固有

- まとまった解説ドキュメントを求められた場合は、まず出力方法を依頼者に質問すること（チャットで答えれば済む質問にはそのまま答える）。選択肢は次の3つ：
  - `html-ghostty-browser` スキル：HTML の説明ドキュメントを作成し、`ghostty-browser` コマンドで Ghostty の新規タブに表示する（macOS + Ghostty 専用）。ローカルに残る
  - `html` スキル：HTML の説明ドキュメントを作成する。表示はせず保存先パスを伝える。ローカルに残る
  - Claude のアーティファクト：claude.ai 上でホストされるページとして出力する
