from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin, UserMixin


class PlatformTenantModel(ModelMixin, UserMixin):
    """租户定义（平台级，自身不受租户过滤——无 TenantMixin）。

    id=1 固定为「默认租户」：存量数据回填与超管平台面均引用它（server_default='1' 的对端）。
    """

    __tablename__: str = "platform_tenant"
    __table_args__: dict[str, str] = {"comment": "平台租户定义表"}

    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="租户名称")
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, comment="租户编码")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None, comment="备注")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态: 0=正常,1=停用")
