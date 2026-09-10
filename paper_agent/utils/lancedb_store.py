import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class LanceDBDependencyError(ImportError):
    """LanceDB 相关依赖未安装。"""


class LanceDBPathError(ValueError):
    """LanceDB 子库路径不符合 papers 根目录限制。"""


class LanceDBSchemaError(ValueError):
    """LanceDB 表结构不符合论文分段表约定。"""


class LanceDBPaperStore:
    """管理 papers 目录下的 LanceDB 论文分段库。"""

    DEFAULT_DATABASE_NAME = "vector_store"
    DEFAULT_TABLE_NAME = "paper_sections"
    VECTOR_DIMENSION = 1024

    def __init__(
        self,
        root_path: Optional[str] = None,
        database_name: str = DEFAULT_DATABASE_NAME,
        table_name: str = DEFAULT_TABLE_NAME,
    ) -> None:
        self.project_root = Path(__file__).resolve().parents[2]
        self.papers_root = (self.project_root / "papers").resolve()
        default_root = self.papers_root / "lancedb"
        configured_root = root_path or os.environ.get("LANCEDB_PAPERS_PATH") or default_root
        self.root_path = Path(configured_root).expanduser().resolve()
        self._validate_root_path()
        self.database_name = database_name
        self.table_name = table_name
        self.database_path = self._resolve_database_path(database_name)
        self._database = None

    def _validate_root_path(self) -> None:
        """LanceDB 根目录只能位于项目 papers 目录内。"""
        try:
            self.root_path.relative_to(self.papers_root)
        except ValueError as exc:
            raise LanceDBPathError(
                f"LANCEDB_PAPERS_PATH 必须位于 papers 目录内：{self.papers_root}"
            ) from exc

    def _resolve_database_path(self, database_name: str) -> Path:
        """只允许简单子库名，防止访问 papers 根目录之外的位置。"""
        if not database_name or database_name in {".", ".."}:
            raise LanceDBPathError("LanceDB 子库名不能为空，也不能是相对目录标记")
        if Path(database_name).is_absolute() or Path(database_name).name != database_name:
            raise LanceDBPathError("LanceDB 子库名不能包含绝对路径或目录分隔符")

        database_path = (self.root_path / database_name).resolve()
        try:
            database_path.relative_to(self.root_path)
        except ValueError as exc:
            raise LanceDBPathError("LanceDB 子库必须位于 papers 根目录内") from exc
        if database_path == self.root_path:
            raise LanceDBPathError("必须使用 papers 根目录下的子库")
        return database_path

    @staticmethod
    def _load_dependencies():
        """按需加载依赖，避免影响项目中不使用 LanceDB 的功能。"""
        try:
            import lancedb
            import pyarrow as pa
        except ImportError as exc:
            raise LanceDBDependencyError(
                "使用 LanceDB 论文库前请安装依赖：pip install lancedb pyarrow"
            ) from exc
        return lancedb, pa

    @classmethod
    def schema(cls):
        """返回空论文分段表使用的标准 Arrow Schema。"""
        _, pa = cls._load_dependencies()
        return pa.schema(
            [
                pa.field("paper_id", pa.int64()),
                pa.field("title", pa.string()),
                pa.field("authors", pa.string()),
                pa.field("url", pa.string()),
                pa.field("abstract", pa.string()),
                pa.field("field", pa.string()),
                pa.field("gene_keywords", pa.string()),
                pa.field("image_path", pa.string()),
                pa.field("section_text", pa.string()),
                pa.field("embedding_text", pa.string()),
                pa.field("embedding_model", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), cls.VECTOR_DIMENSION)),
            ]
        )

    def connect(self):
        """连接指定子库；不会创建表或写入论文记录。"""
        lancedb, _ = self._load_dependencies()
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.database_path.mkdir(parents=False, exist_ok=True)
        self._database = lancedb.connect(str(self.database_path))
        return self._database

    @property
    def database(self):
        if self._database is None:
            return self.connect()
        return self._database

    def list_tables(self) -> List[str]:
        """兼容不同 LanceDB 版本的表名查询接口。"""
        database = self.database
        if hasattr(database, "list_tables"):
            result = database.list_tables()
            return list(result.tables if hasattr(result, "tables") else result)
        return list(database.table_names())

    def create_table(self, table_name: Optional[str] = None):
        """创建空表；若表已存在则直接打开，绝不覆盖已有数据。"""
        resolved_name = table_name or self.table_name
        if resolved_name in self.list_tables():
            return self.open_table(resolved_name)
        return self.database.create_table(resolved_name, schema=self.schema())

    def open_table(self, table_name: Optional[str] = None):
        resolved_name = table_name or self.table_name
        if resolved_name not in self.list_tables():
            raise KeyError(f"LanceDB 表不存在：{resolved_name}")
        return self.database.open_table(resolved_name)

    def validate_schema(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """校验已有表字段，返回缺失字段和类型冲突，方便部署前检查。"""
        table = self.open_table(table_name)
        expected = {field.name: str(field.type) for field in self.schema()}
        actual_schema = table.schema() if callable(table.schema) else table.schema
        actual = {field.name: str(field.type) for field in actual_schema}
        missing_fields = sorted(set(expected) - set(actual))
        type_mismatches = {
            name: {"expected": expected[name], "actual": actual[name]}
            for name in expected.keys() & actual.keys()
            if expected[name] != actual[name]
        }
        return {
            "valid": not missing_fields and not type_mismatches,
            "missing_fields": missing_fields,
            "type_mismatches": type_mismatches,
        }

    def ensure_schema(self, allow_recreate_empty: bool = True):
        """Open a valid table, or safely recreate an incompatible empty table."""
        if self.table_name not in self.list_tables():
            return self.create_table()

        table = self.open_table()
        status = self.validate_schema()
        if status["valid"]:
            return table

        row_count = table.count_rows()
        if row_count:
            raise LanceDBSchemaError(
                "LanceDB paper_sections Schema 不兼容且表中已有数据，拒绝覆盖；"
                f"rows={row_count}, missing={status['missing_fields']}, "
                f"type_mismatches={status['type_mismatches']}"
            )
        if not allow_recreate_empty:
            raise LanceDBSchemaError(
                "LanceDB paper_sections Schema 不兼容，且未允许重建空表"
            )

        self.database.drop_table(self.table_name)
        return self.create_table()

    def upsert_sections(self, records: List[Dict[str, Any]]) -> int:
        """Idempotently replace one abstract-level section per paper."""
        if not records:
            return 0
        table = self.ensure_schema()
        for record in records:
            paper_id = int(record["paper_id"])
            vector = record.get("vector")
            if vector is None or len(vector) != self.VECTOR_DIMENSION:
                raise LanceDBSchemaError(
                    f"paper_id={paper_id} 的向量维度必须为 {self.VECTOR_DIMENSION}"
                )
            table.delete(f"paper_id = {paper_id}")
            table.add([record])
        return len(records)

    def paper_ids(self) -> List[int]:
        """Return all stored paper ids for cross-store verification."""
        table = self.ensure_schema()
        if table.count_rows() == 0:
            return []
        values = table.to_arrow().column("paper_id").to_pylist()
        return [int(value) for value in values]

    def health_check(self) -> Dict[str, Any]:
        """检查目录和连接状态；失败时返回错误信息而不吞掉上下文。"""
        try:
            tables = self.list_tables()
            return {
                "ok": True,
                "root_path": str(self.root_path),
                "database_path": str(self.database_path),
                "tables": tables,
            }
        except Exception as exc:
            return {
                "ok": False,
                "root_path": str(self.root_path),
                "database_path": str(self.database_path),
                "tables": [],
                "error": str(exc),
            }

    def initialize(self) -> Dict[str, Any]:
        """初始化本地子库和空表，并返回可用于部署日志的结果。"""
        self._validate_root_path()
        self.connect()
        table_existed = self.table_name in self.list_tables()
        table = self.ensure_schema()
        schema_status = self.validate_schema()
        result = self.health_check()
        result["table"] = self.table_name
        result["schema"] = schema_status
        result["created_empty_table"] = not table_existed and table is not None
        return result
