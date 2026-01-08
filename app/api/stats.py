# app/api/stats.py
from fastapi import APIRouter, HTTPException, Query, Depends
from app.core.auth import get_current_admin
from app.core import (
    ENCRYPTED_DIR, DECRYPTED_DIR, UPLOAD_DIR, 
    file_storage, cleanup_manager, audit_logger
)
from pathlib import Path
import os
import time
import hashlib
from datetime import datetime, timedelta
import platform
import psutil
import json

router = APIRouter()

@router.get("/stats")
async def get_system_stats(current_user: str = Depends(get_current_admin)):
    """Получить полную статистику системы"""
    print(f"📊 Запрос статистики системы")
    
    try:
        stats = await _collect_all_stats()
        return stats
    except Exception as e:
        print(f"❌ Ошибка сбора статистики: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to collect stats: {str(e)}")

async def _collect_all_stats():
    """Сбор всей статистики системы"""
    stats = {
        "timestamp": datetime.now().isoformat(),
        "system": await _get_system_stats(),
        "storage": await _get_storage_stats(),
        "files": await _get_files_stats(),
        "cleanup": await _get_cleanup_stats(),
        "audit": await _get_audit_stats(),
        "performance": await _get_performance_stats()
    }
    
    # Общая сводка
    stats["summary"] = {
        "total_files": stats["files"]["encrypted"]["count"],
        "total_size_mb": stats["storage"]["total_size_mb"],
        "uptime": stats["system"]["uptime"],
        "health": "healthy" if stats["files"]["encrypted"]["count"] >= 0 else "degraded"
    }
    
    return stats


async def _get_system_stats():
    """Статистика системы с защитой от ошибок в контейнеризированных средах (Docker)"""
    
    # Базовая информация о системе — почти всегда доступна
    system_info = {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
        "processor": platform.processor() or "Unknown",
    }
    
    stats = {
        "system": system_info,
        "cpu": {},
        "memory": {},
        "disk": {},
        "uptime": "unavailable"
    }
    
    # --- CPU статистика ---
    try:
        stats["cpu"]["percent"] = psutil.cpu_percent(interval=0.1)
        stats["cpu"]["count"] = psutil.cpu_count(logical=True)
        stats["cpu"]["physical_count"] = psutil.cpu_count(logical=False)
    except Exception as e:
        print(f"⚠️ psutil.cpu_* недоступен (вероятно, Docker): {e}")
        stats["cpu"]["percent"] = "unavailable_in_container"
        stats["cpu"]["count"] = "unavailable_in_container"
    
    try:
        # getloadavg() часто недоступен в Docker
        if hasattr(psutil, 'getloadavg'):
            stats["cpu"]["load_avg"] = psutil.getloadavg()
        else:
            stats["cpu"]["load_avg"] = "not_supported"
    except Exception as e:
        print(f"⚠️ psutil.getloadavg() недоступен: {e}")
        stats["cpu"]["load_avg"] = "unavailable_in_container"
    
    # --- Память ---
    try:
        memory = psutil.virtual_memory()
        stats["memory"] = {
            "total_gb": round(memory.total / (1024**3), 2),
            "available_gb": round(memory.available / (1024**3), 2),
            "used_gb": round(memory.used / (1024**3), 2),
            "percent": memory.percent
        }
    except Exception as e:
        print(f"⚠️ psutil.virtual_memory() недоступен: {e}")
        stats["memory"] = {"error": "unavailable_in_container"}
    
    # --- Диск ---
    try:
        disk = psutil.disk_usage('/')
        stats["disk"] = {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": disk.percent
        }
    except Exception as e:
        print(f"⚠️ psutil.disk_usage() недоступен: {e}")
        stats["disk"] = {"error": "unavailable_in_container"}
    
    # --- Uptime системы ---
    try:
        boot_time = psutil.boot_time()
        stats["uptime"] = round(time.time() - boot_time, 0)
    except Exception as e:
        print(f"⚠️ psutil.boot_time() недоступен: {e}")
        stats["uptime"] = "unavailable_in_container"
    
    return stats

async def _get_storage_stats():
    """Статистика хранилища"""
    directories = {
        "encrypted": ENCRYPTED_DIR,
        "decrypted": DECRYPTED_DIR,
        "uploads": UPLOAD_DIR,
        "keys": Path("keys"),
        "audit_logs": Path("audit_logs"),
        "static": Path("static")
    }
    
    storage_stats = {}
    total_size = 0
    total_files = 0
    
    for name, directory in directories.items():
        dir_stats = await _get_directory_stats(directory)
        storage_stats[name] = dir_stats
        total_size += dir_stats["size_bytes"]
        total_files += dir_stats["file_count"]
    
    return {
        "directories": storage_stats,
        "total_size_bytes": total_size,
        "total_size_mb": total_size / (1024 * 1024),
        "total_size_gb": total_size / (1024 * 1024 * 1024),
        "total_files": total_files
    }

async def _get_directory_stats(directory: Path):
    """Статистика директории"""
    if not directory.exists():
        return {
            "exists": False,
            "size_bytes": 0,
            "file_count": 0,
            "last_modified": None
        }
    
    total_size = 0
    file_count = 0
    last_modified = 0
    
    try:
        for item in directory.rglob('*'):
            if item.is_file():
                try:
                    stat = item.stat()
                    total_size += stat.st_size
                    file_count += 1
                    last_modified = max(last_modified, stat.st_mtime)
                except:
                    continue
        
        return {
            "exists": True,
            "path": str(directory.absolute()),
            "size_bytes": total_size,
            "file_count": file_count,
            "last_modified": datetime.fromtimestamp(last_modified).isoformat() if last_modified > 0 else None
        }
    except Exception as e:
        return {
            "exists": True,
            "error": str(e),
            "size_bytes": 0,
            "file_count": 0
        }

async def _get_files_stats():
    """Статистика файлов"""
    encrypted_files = []
    if ENCRYPTED_DIR.exists():
        for file_path in ENCRYPTED_DIR.iterdir():
            if file_path.is_file():
                try:
                    stat = file_path.stat()
                    encrypted_files.append({
                        "name": file_path.name,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "age_days": (time.time() - stat.st_mtime) / 86400,
                        "extension": file_path.suffix
                    })
                except:
                    continue
    
    # Группировка по расширениям
    extensions = {}
    for file_info in encrypted_files:
        ext = file_info["extension"] or "no_extension"
        if ext not in extensions:
            extensions[ext] = {"count": 0, "total_size": 0}
        extensions[ext]["count"] += 1
        extensions[ext]["total_size"] += file_info["size"]
    
    # Самые старые и новые файлы
    encrypted_files_sorted = sorted(encrypted_files, key=lambda x: x["modified"])
    oldest_files = encrypted_files_sorted[:5] if encrypted_files_sorted else []
    newest_files = encrypted_files_sorted[-5:] if encrypted_files_sorted else []
    
    # Самые большие файлы
    largest_files = sorted(encrypted_files, key=lambda x: x["size"], reverse=True)[:5]
    
    return {
        "encrypted": {
            "count": len(encrypted_files),
            "total_size": sum(f["size"] for f in encrypted_files),
            "extensions": extensions,
            "oldest_files": oldest_files,
            "newest_files": newest_files,
            "largest_files": largest_files
        },
        "temporary": file_storage.get_stats() if hasattr(file_storage, 'get_stats') else {}
    }

async def _get_cleanup_stats():
    """Статистика очистки"""
    try:
        # Статистика от cleanup_manager
        cleanup_stats = cleanup_manager.get_cleanup_stats() if hasattr(cleanup_manager, 'get_cleanup_stats') else {}
        
        # Файлы для удаления
        files_to_delete = []
        if ENCRYPTED_DIR.exists():
            current_time = time.time()
            for file_path in ENCRYPTED_DIR.iterdir():
                if file_path.is_file():
                    try:
                        file_age = current_time - file_path.stat().st_atime
                        if file_age > 30 * 86400:  # 30 дней
                            files_to_delete.append({
                                "name": file_path.name,
                                "size": file_path.stat().st_size,
                                "age_days": file_age / 86400
                            })
                    except:
                        continue
        
        return {
            "cleanup_manager": cleanup_stats,
            "files_scheduled_for_deletion": {
                "count": len(files_to_delete),
                "total_size": sum(f["size"] for f in files_to_delete),
                "files": sorted(files_to_delete, key=lambda x: x["age_days"], reverse=True)[:10]
            },
            "temporary_files": file_storage.get_stats() if hasattr(file_storage, 'get_stats') else {},
            "retention_policy": {
                "text_files_days": 30,
                "pdf_files_days": 90,
                "image_files_days": 180,
                "dicom_files_days": 365,
                "default_days": 30
            }
        }
    except Exception as e:
        return {"error": str(e)}

async def _get_audit_stats():
    """Статистика аудита"""
    try:
        # Получаем логи за последние 7 дней
        log_files = []
        audit_dir = Path("audit_logs")
        
        if audit_dir.exists():
            for log_file in audit_dir.iterdir():
                if log_file.is_file() and log_file.name.endswith('.log'):
                    log_files.append({
                        "name": log_file.name,
                        "size": log_file.stat().st_size,
                        "modified": datetime.fromtimestamp(log_file.stat().st_mtime).isoformat()
                    })
        
        # Анализ логов (если есть доступ)
        log_analysis = {
            "total_log_files": len(log_files),
            "total_log_size": sum(f["size"] for f in log_files),
            "recent_logs": sorted(log_files, key=lambda x: x["modified"], reverse=True)[:5]
        }
        
        # Попробуем проанализировать последний лог-файл
        if log_files:
            latest_log = max(log_files, key=lambda x: x["modified"])
            log_path = audit_dir / latest_log["name"]
            
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    log_analysis["latest_log"] = {
                        "name": latest_log["name"],
                        "line_count": len(lines),
                        "sample_lines": lines[-5:] if lines else []
                    }
            except:
                log_analysis["latest_log"] = {"error": "Could not read log file"}
        
        return log_analysis
    except Exception as e:
        return {"error": str(e)}

async def _get_performance_stats():
    """Статистика производительности"""
    # Здесь можно добавить метрики производительности
    # Например, среднее время операций, количество запросов и т.д.
    
    return {
        "encryption_performance": {
            "note": "Metrics would be collected over time",
            "average_encryption_time_ms": "N/A",
            "average_decryption_time_ms": "N/A"
        },
        "api_usage": {
            "note": "API usage statistics would be implemented",
            "total_requests": "N/A",
            "requests_per_endpoint": {}
        }
    }

@router.get("/stats/summary")
async def get_stats_summary(current_key: str = Depends(get_current_admin)):
    """Краткая сводка статистики"""
    try:
        full_stats = await _collect_all_stats()
        
        summary = {
            "timestamp": full_stats["timestamp"],
            "health": "healthy",
            "total_files": full_stats["summary"]["total_files"],
            "total_size_mb": round(full_stats["summary"]["total_size_mb"], 2),
            "uptime_hours": round(full_stats["system"]["uptime"] / 3600, 1),
            "directories": {
                name: {
                    "files": stats["file_count"],
                    "size_mb": round(stats["size_bytes"] / (1024 * 1024), 2)
                }
                for name, stats in full_stats["storage"]["directories"].items()
            },
            "file_types": {
                ext: data["count"]
                for ext, data in full_stats["files"]["encrypted"]["extensions"].items()
            },
            "cleanup": {
                "files_to_delete": full_stats["cleanup"]["files_scheduled_for_deletion"]["count"],
                "temporary_files": full_stats["cleanup"]["temporary_files"].get("total_files", 0)
            }
        }
        
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}")

@router.get("/stats/health")
async def get_health_detailed(current_key: str = Depends(get_current_admin)):
    """Детальная проверка здоровья системы"""
    
    health_checks = []
    
    # Проверка директорий
    required_dirs = [
        ("encrypted", ENCRYPTED_DIR),
        ("keys", Path("keys")),
        ("static", Path("static"))
    ]
    
    for name, directory in required_dirs:
        check = {
            "check": f"Directory {name}",
            "status": "healthy" if directory.exists() else "unhealthy",
            "details": {
                "exists": directory.exists(),
                "path": str(directory.absolute())
            }
        }
        health_checks.append(check)
    
    # Проверка ключей
    key_file = Path("keys/age.key")
    key_check = {
        "check": "Encryption keys",
        "status": "healthy" if key_file.exists() and key_file.stat().st_size > 0 else "unhealthy",
        "details": {
            "exists": key_file.exists(),
            "size": key_file.stat().st_size if key_file.exists() else 0
        }
    }
    health_checks.append(key_check)
    
    # Проверка доступа к файлам
    try:
        if ENCRYPTED_DIR.exists():
            test_file_count = len(list(ENCRYPTED_DIR.iterdir()))
            access_check = {
                "check": "File system access",
                "status": "healthy",
                "details": {
                    "encrypted_files": test_file_count,
                    "can_read": True
                }
            }
        else:
            access_check = {
                "check": "File system access",
                "status": "unhealthy",
                "details": {"error": "Encrypted directory not found"}
            }
        health_checks.append(access_check)
    except Exception as e:
        health_checks.append({
            "check": "File system access",
            "status": "unhealthy",
            "details": {"error": str(e)}
        })
    
    # Определение общего статуса
    all_healthy = all(check["status"] == "healthy" for check in health_checks)
    
    return {
        "timestamp": datetime.now().isoformat(),
        "overall_status": "healthy" if all_healthy else "degraded",
        "checks": health_checks,
        "recommendations": [
            "Ensure all required directories exist",
            "Check disk space regularly",
            "Monitor audit logs for suspicious activity"
        ] if all_healthy else [
            "Fix missing directories",
            "Check file permissions",
            "Verify encryption keys"
        ]
    }