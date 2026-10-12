import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class LanceDBDependencyError(ImportError):
    """LanceDB 相关依赖未安装。"""


class LanceDBPathError(ValueError):
    """LanceDB 子库路径不符合 papers 根目录限制。"""


class LanceDBSchemaError(ValueError):
    """LanceDB 表结构不符合精简论文向量表约定。"""


class LanceDBPaperStore:
    """管理 papers 目录下的精简论文向量库。"""

    DEFAULT_DATABASE_NAME = "vector_store"
    DEFAULT_TABLE_NAME = "paper_embeddings"
    LEGACY_TABLE_NAME = "paper_sections"
    VECTOR_DIMENSION = 1024

    def __init__(
        self,
        root_path: Optional[str] = None,
        database_name: str = DEFAULT_DATABASE_NAME,
        table_name: str = DEFAULT_TABLE_NAME,
    ) -> None:
        """解析并校验本地存储路径，记录目标子库和表名。"""
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
    def _load_dependencies() -> Any:
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
    def schema(cls) -> Any:
        """返回精简论文向量表使用的六字段 Arrow Schema。"""
        _, pa = cls._load_dependencies()
        return pa.schema(
            [
                pa.field("paper_id", pa.int64(), nullable=False),
                pa.field("title", pa.string(), nullable=False),
                pa.field("abstract", pa.string(), nullable=False),
                pa.field("embedding_text", pa.string(), nullable=False),
                pa.field("embedding_model", pa.string(), nullable=False),
                pa.field(
                    "vector",
                    pa.list_(pa.float32(), cls.VECTOR_DIMENSION),
                    nullable=False,
                ),
            ]
        )

    def connect(self) -> Any:
        """连接指定子库；不会创建表或写入论文记录。"""
        lancedb, _ = self._load_dependencies()
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.database_path.mkdir(parents=False, exist_ok=True)
        self._database = lancedb.connect(str(self.database_path))
        return self._database

    @property
    def database(self) -> Any:
        """返回已建立的数据库连接，尚未连接时自动初始化。"""
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

    def create_table(self, table_name: Optional[str] = None) -> Any:
        """创建空表；若表已存在则直接打开，绝不覆盖已有数据。"""
        resolved_name = table_name or self.table_name
        if resolved_name in self.list_tables():
            return self.open_table(resolved_name)
        return self.database.create_table(resolved_name, schema=self.schema())

    def open_table(self, table_name: Optional[str] = None) -> Any:
        """打开指定论文表；表不存在时明确报错而不自动创建。"""
        resolved_name = table_name or self.table_name
        if resolved_name not in self.list_tables():
            raise KeyError(f"LanceDB 表不存在：{resolved_name}")
        return self.database.open_table(resolved_name)

    def validate_schema(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """校验字段名称、类型及可空性是否与六字段 Schema 完全一致。

        参数:
            table_name: 可选表名；为空时校验当前目标表。

        返回:
            包含有效标志、缺失字段、额外字段和类型冲突的字典。

        异常:
            KeyError: 目标表不存在。
        """
        table = self.open_table(table_name)
        expected = {
            field.name: (str(field.type), field.nullable) for field in self.schema()
        }
        actual_schema = table.schema() if callable(table.schema) else table.schema
        actual = {
            field.name: (str(field.type), field.nullable) for field in actual_schema
        }
        missing_fields = sorted(set(expected) - set(actual))
        unexpected_fields = sorted(set(actual) - set(expected))
        type_mismatches = {
            name: {
                "expected": {
                    "type": expected[name][0],
                    "nullable": expected[name][1],
                },
                "actual": {
                    "type": actual[name][0],
                    "nullable": actual[name][1],
                },
            }
            for name in expected.keys() & actual.keys()
            if expected[name] != actual[name]
        }
        return {
            "valid": not missing_fields
            and not unexpected_fields
            and not type_mismatches,
            "missing_fields": missing_fields,
            "unexpected_fields": unexpected_fields,
            "type_mismatches": type_mismatches,
        }

    def ensure_schema(self, allow_recreate_empty: bool = True) -> Any:
        """确保表结构有效，只允许安全重建结构不兼容的空表。

        参数:
            allow_recreate_empty: 是否允许重建结构不兼容的空表。

        返回:
            结构有效的 LanceDB 表对象。

        异常:
            LanceDBSchemaError: 非空表结构不兼容，或禁止重建空表。
        """
        if self.table_name not in self.list_tables():
            return self.create_table()

        table = self.open_table()
        status = self.validate_schema()
        if status["valid"]:
            return table

        row_count = table.count_rows()
        if row_count:
            raise LanceDBSchemaError(
                f"LanceDB {self.table_name} Schema 不兼容且表中已有数据，拒绝覆盖；"
                f"rows={row_count}, missing={status['missing_fields']}, "
                f"unexpected={status['unexpected_fields']}, "
                f"type_mismatches={status['type_mismatches']}"
            )
        if not allow_recreate_empty:
            raise LanceDBSchemaError(
                f"LanceDB {self.table_name} Schema 不兼容，且未允许重建空表"
            )

        self.database.drop_table(self.table_name)
        return self.create_table()

    def _validate_record(self, record: Dict[str, Any]) -> None:
        """校验单条向量记录的必填字段、维度、有限性和归一化结果。

        参数:
            record: 待写入 ``paper_embeddings`` 的单条记录。

        返回:
            校验通过时不返回内容。

        异常:
            LanceDBSchemaError: 字段缺失、文本为空或向量不合规。
        """
        required = {
            "paper_id",
            "title",
            "abstract",
            "embedding_text",
            "embedding_model",
            "vector",
        }
        missing = sorted(required - set(record))
        if missing:
            raise LanceDBSchemaError(f"向量记录缺少字段：{missing}")

        paper_id = int(record["paper_id"])
        for field_name in (
            "title",
            "abstract",
            "embedding_text",
            "embedding_model",
        ):
            if not isinstance(record[field_name], str) or not record[field_name].strip():
                raise LanceDBSchemaError(
                    f"paper_id={paper_id} 的 {field_name} 不能为空"
                )
        vector = record["vector"]
        if not isinstance(vector, (list, tuple)) or len(vector) != self.VECTOR_DIMENSION:
            raise LanceDBSchemaError(
                f"paper_id={paper_id} 的向量维度必须为 {self.VECTOR_DIMENSION}"
            )
        values = [float(value) for value in vector]
        if any(not math.isfinite(value) for value in values):
            raise LanceDBSchemaError(f"paper_id={paper_id} 的向量包含非法数值")
        norm = math.sqrt(sum(value * value for value in values))
        if not math.isclose(norm, 1.0, rel_tol=1e-4, abs_tol=1e-4):
            raise LanceDBSchemaError(
                f"paper_id={paper_id} 的向量未完成 L2 归一化，范数={norm}"
            )

    def upsert_embeddings(self, records: List[Dict[str, Any]]) -> int:
        """按 paper_id 幂等写入每篇论文的一条精简向量记录。

        参数:
            records: 已通过向量化步骤生成的六字段记录列表。

        返回:
            本批提交的记录数量。

        异常:
            LanceDBSchemaError: 记录无效、批内 ID 重复或表结构不兼容。
        """
        if not records:
            return 0
        for record in records:
            self._validate_record(record)

        paper_ids = [int(record["paper_id"]) for record in records]
        if len(set(paper_ids)) != len(paper_ids):
            raise LanceDBSchemaError("同一批向量记录中 paper_id 不能重复")

        table = self.ensure_schema()
        if hasattr(table, "merge_insert"):
            (
                table.merge_insert("paper_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(records)
            )
            return len(records)

        # 兼容较旧的 LanceDB：逐篇先删后加，仍保持 paper_id 幂等。
        for record in records:
            paper_id = int(record["paper_id"])
            table.delete(f"paper_id = {paper_id}")
            table.add([record])
        return len(records)

    def upsert_sections(self, records: List[Dict[str, Any]]) -> int:
        """兼容旧调用名称，并转发到精简向量表写入实现。"""
        return self.upsert_embeddings(records)

    def paper_ids(self) -> List[int]:
        """返回全部论文 ID，用于与 MySQL 做跨库一致性校验。"""
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
