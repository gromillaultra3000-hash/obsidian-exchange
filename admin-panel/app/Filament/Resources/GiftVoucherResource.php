<?php

namespace App\Filament\Resources;

use App\Filament\Resources\GiftVoucherResource\Pages;
use App\Models\GiftVoucher;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Tables;
use Filament\Tables\Table;

class GiftVoucherResource extends ReadOnlyResource
{
    protected static ?string $model = GiftVoucher::class;

    protected static ?string $navigationIcon = 'heroicon-o-gift';

    protected static ?string $navigationLabel = 'Подарочные ваучеры';

    protected static ?string $modelLabel = 'ваучер';

    protected static ?string $pluralModelLabel = 'ваучеры';

    protected static ?string $navigationGroup = 'Торговля';

    protected static ?int $navigationSort = 6;

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\TextInput::make('sender_id')
                    ->label('Отправитель (User ID)')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('recipient_id')
                    ->label('Получатель (User ID)')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('currency')
                    ->label('Валюта')
                    ->disabled(),
                Forms\Components\TextInput::make('rub_amount')
                    ->label('Сумма, RUB')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('code')
                    ->label('Код ваучера')
                    ->disabled()
                    ->columnSpanFull(),
                Forms\Components\TextInput::make('status')
                    ->label('Статус')
                    ->disabled(),
                Forms\Components\TextInput::make('order_id')
                    ->label('Order ID')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('recipient_address')
                    ->label('Адрес получателя')
                    ->disabled()
                    ->columnSpanFull(),
                Forms\Components\TextInput::make('created_at')
                    ->label('Создано')
                    ->disabled(),
                Forms\Components\TextInput::make('claimed_at')
                    ->label('Активирован')
                    ->disabled(),
            ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->defaultSort('id', 'desc')
            ->columns([
                Tables\Columns\TextColumn::make('id')
                    ->label('#')
                    ->sortable(),
                Tables\Columns\TextColumn::make('sender_id')
                    ->label('Отправитель')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('recipient_id')
                    ->label('Получатель')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('currency')
                    ->label('Валюта')
                    ->badge(),
                Tables\Columns\TextColumn::make('rub_amount')
                    ->label('Сумма, RUB')
                    ->numeric(2)
                    ->sortable(),
                Tables\Columns\TextColumn::make('code')
                    ->label('Код')
                    ->searchable()
                    ->copyable(),
                Tables\Columns\TextColumn::make('status')
                    ->label('Статус')
                    ->badge()
                    ->color(fn (string $state): string => match ($state) {
                        'claimed' => 'success',
                        'pending' => 'gray',
                        'expired' => 'warning',
                        'cancelled' => 'danger',
                        default => 'gray',
                    })
                    ->sortable(),
                Tables\Columns\TextColumn::make('claimed_at')
                    ->label('Активирован')
                    ->dateTime('d.m.Y H:i')
                    ->sortable()
                    ->toggleable(),
                Tables\Columns\TextColumn::make('created_at')
                    ->label('Создано')
                    ->dateTime('d.m.Y H:i')
                    ->sortable(),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('status')
                    ->label('Статус')
                    ->options([
                        'pending' => 'pending',
                        'claimed' => 'claimed',
                        'expired' => 'expired',
                        'cancelled' => 'cancelled',
                    ]),
                Tables\Filters\SelectFilter::make('currency')
                    ->label('Валюта')
                    ->options([
                        'BTC' => 'BTC',
                        'LTC' => 'LTC',
                        'USDT' => 'USDT',
                        'ETH' => 'ETH',
                    ]),
            ])
            ->actions([
                Tables\Actions\ViewAction::make(),
            ])
            ->bulkActions([]);
    }

    public static function canCreate(): bool
    {
        return false;
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListGiftVouchers::route('/'),
        ];
    }
}
