module.exports = {
    apps: [
        {
            name: "analysis",
            script: "periodic_analysis.py",
            interpreter: "/home/koreacores/backend_0621/venv_py3.12/bin/python",
            instances: 1,
            autorestart: true,
            watch: false,
            cwd: "/home/koreacores/backend_0621",
            env: {
                PYTHONUNBUFFERED: "1",
                VIRTUAL_ENV: "/home/koreacores/backend_0621/venv_py3.12",
                PATH: "/home/koreacores/backend_0621/venv_py3.12/bin:$PATH"
            },
            log_file: "/home/koreacores/backend_0621/analysis.out",
            out_file: "/home/koreacores/backend_0621/analysis.out",
            error_file: "/home/koreacores/backend_0621/analysis.out"
        }
    ]
};