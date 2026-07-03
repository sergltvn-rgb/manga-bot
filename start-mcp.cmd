@echo off
title Notion MCP Auto-Bridge
cd /d "%~dp0"
echo ==========================================
echo Starting Notion MCP Auto-Bridge...
echo ==========================================
node start-mcp.cjs
pause
